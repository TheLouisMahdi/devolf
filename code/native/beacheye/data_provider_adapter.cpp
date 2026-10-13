#include "data_provider_adapter.h"

#include <winsock2.h>
#include <ws2tcpip.h>

#include <algorithm>
#include <climits>
#include <chrono>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <regex>
#include <string>
#include <thread>
#include <vector>

#include "bridge.h"
#ifdef TRUE
#undef TRUE
#endif
#include "crc.h"
#include "ls_config.h"

namespace {
constexpr uint8_t FRAME_FILE_FIRMWARE = 0x09;
constexpr uint8_t FRAME_FILE_BOOTLOADER = 0x0A;
constexpr uint8_t FRAME_CHECK_UPDATE_FIRMWARE = 0x0B;
constexpr uint8_t FRAME_CHECK_UPDATE_BOOTLOADER = 0x0C;
constexpr uint8_t FRAME_UPDATE_FIRMWARE_SIGNAL = 0x0D;
constexpr uint8_t FRAME_UPDATE_BOOTLOADER_SIGNAL = 0x0E;
constexpr uint8_t STATUS_RESETTING = 0x02;
constexpr uint8_t STATUS_FILE_FRAME_UPLOAD_SUCCESS = 0x04;
constexpr uint8_t STATUS_FILE_WRITE_SUCCESS = 0x05;
constexpr uint8_t STATUS_FILE_WRITE_ERROR = 0x06;
constexpr uint8_t STATUS_NO_NEED_UPLOAD = 0x09;
constexpr uint8_t FILE_FLAG_FIRST_PART = 0x01;
constexpr uint8_t FILE_FLAG_LAST_PART = 0x02;
constexpr size_t FILE_CHUNK_SIZE = MAX_DATA_SIZE - 4;
constexpr uint32_t INTERNAL_UPDATE_CHECK_EXISTING = 0xFFFFFF01u;
constexpr uint32_t INTERNAL_UPDATE_UPLOAD_PART = 0xFFFFFF02u;
constexpr uint32_t INTERNAL_UPDATE_CHECK_UPLOADED = 0xFFFFFF03u;
constexpr uint32_t INTERNAL_UPDATE_SIGNAL = 0xFFFFFF04u;

struct Request {
    uint32_t tag;
    uint8_t frame_type;
    std::vector<uint8_t> payload;
};

struct Pending {
    Request request;
    uint8_t sequence;
    std::chrono::steady_clock::time_point deadline;
};

class Provider {
public:
    Provider(BEProviderCallback callback, void* context)
        : callback_(callback), context_(context) {}

    ~Provider() {
        stop();
        if (worker_.joinable() && worker_.get_id() != std::this_thread::get_id()) worker_.join();
    }

    int start(const char* ip, uint16_t port, uint32_t timeout_ms, bool legacy_protocol) {
        if (!ip || !*ip || !port) return fail("Invalid native provider endpoint.");
        stop();
        join_worker();

        static std::once_flag winsock_once;
        static int winsock_result = WSASYSNOTREADY;
        std::call_once(winsock_once, [] {
            WSADATA data{};
            winsock_result = WSAStartup(MAKEWORD(2, 2), &data);
        });
        if (winsock_result != 0) return fail("Winsock initialization failed.");

        addrinfo hints{};
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        hints.ai_protocol = IPPROTO_TCP;
        addrinfo* addresses = nullptr;
        const std::string service = std::to_string(port);
        if (getaddrinfo(ip, service.c_str(), &hints, &addresses) != 0) {
            return fail("The native provider could not resolve the device address.");
        }

        SOCKET connected = INVALID_SOCKET;
        for (addrinfo* address = addresses; address; address = address->ai_next) {
            SOCKET candidate = socket(address->ai_family, address->ai_socktype, address->ai_protocol);
            if (candidate == INVALID_SOCKET) continue;
            u_long nonblocking = 1;
            ioctlsocket(candidate, FIONBIO, &nonblocking);
            const int result = connect(candidate, address->ai_addr, static_cast<int>(address->ai_addrlen));
            if (result == 0 || WSAGetLastError() == WSAEWOULDBLOCK) {
                fd_set writable;
                FD_ZERO(&writable);
                FD_SET(candidate, &writable);
                timeval timeout{
                    static_cast<long>(timeout_ms / 1000),
                    static_cast<long>((timeout_ms % 1000) * 1000),
                };
                if (select(0, nullptr, &writable, nullptr, &timeout) > 0) {
                    int error = 0;
                    int length = sizeof(error);
                    getsockopt(candidate, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &length);
                    if (!error) connected = candidate;
                }
            }
            if (connected != INVALID_SOCKET) break;
            closesocket(candidate);
        }
        freeaddrinfo(addresses);
        if (connected == INVALID_SOCKET) return fail("Native TCP connection failed.");

        u_long blocking = 0;
        ioctlsocket(connected, FIONBIO, &blocking);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            socket_ = connected;
            stop_requested_ = false;
            connected_ = true;
            legacy_protocol_ = legacy_protocol;
            sequence_ = 1;
            receive_buffer_.clear();
            queue_.clear();
            pending_.reset();
            clear_update_locked();
        }
        worker_ = std::thread(&Provider::run, this);
        emit(BE_PROVIDER_CONNECTED, 0, port, nullptr, 0);
        return 0;
    }

    void stop() {
        SOCKET socket = INVALID_SOCKET;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_requested_ = true;
            socket = socket_;
            socket_ = INVALID_SOCKET;
            connected_ = false;
            queue_.clear();
            pending_.reset();
            clear_update_locked();
        }
        if (socket != INVALID_SOCKET) {
            shutdown(socket, SD_BOTH);
            closesocket(socket);
        }
        join_worker();
    }

    int request(uint32_t tag, uint8_t frame_type, const uint8_t* payload, size_t payload_size) {
        if ((payload_size && !payload) || payload_size + 1 > MAX_DATA_SIZE) {
            return fail("Native request payload is invalid or too large.");
        }
        std::lock_guard<std::mutex> lock(mutex_);
        if (!connected_) return -1;
        std::vector<uint8_t> body;
        if (payload_size) body.assign(payload, payload + payload_size);
        queue_.push_back({tag, frame_type, std::move(body)});
        return 0;
    }

    int update_file(uint32_t kind, const wchar_t* path, uint32_t hardware, uint32_t bootloader) {
        if (!path || (kind != BE_PROVIDER_FIRMWARE && kind != BE_PROVIDER_BOOTLOADER)) {
            return fail("Invalid update request.");
        }
        bool legacy = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            legacy = legacy_protocol_;
        }
        if (legacy) return fail_update(kind, "This firmware uses the legacy update protocol.");
        if (bootloader < 2) return fail_update(kind, "Not supported by this device bootloader.");

        std::ifstream stream(std::filesystem::path(path), std::ios::binary);
        if (!stream) return fail_update(kind, "Update file was not found or could not be opened.");
        std::vector<uint8_t> image(
            (std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>()
        );
        if (image.size() < 3 || image.size() - 2 > INT_MAX) {
            return fail_update(kind, "Update file is incomplete or too large.");
        }

        const std::string bytes(reinterpret_cast<const char*>(image.data()), image.size());
        std::smatch match;
        const std::regex version_pattern("DFHB-VER[^A-Za-z0-9]*([^\\x00\\r\\n]+)");
        if (!std::regex_search(bytes, match, version_pattern)) {
            return fail_update(kind, "DFHB-VER marker was not found.");
        }
        const std::string version = match[1].str();
        size_t first = version.find('.');
        size_t second = first == std::string::npos ? first : version.find('.', first + 1);
        size_t third = second == std::string::npos ? second : version.find('.', second + 1);
        if (first == std::string::npos || second == std::string::npos) {
            return fail_update(kind, "DFHB version is malformed.");
        }
        const std::string hardware_text = version.substr(
            second + 1, (third == std::string::npos ? version.size() : third) - second - 1
        );
        char* end = nullptr;
        const unsigned long file_hardware = std::strtoul(hardware_text.c_str(), &end, 10);
        if (!end || *end || file_hardware != hardware) {
            return fail_update(kind, "Update file is not compatible with the device hardware.");
        }

        const uint16_t expected = static_cast<uint16_t>(image[image.size() - 2]) |
            (static_cast<uint16_t>(image.back()) << 8);
        static std::once_flag crc_once;
        std::call_once(crc_once, crcInit);
        const uint16_t actual = crcFast(image.data(), static_cast<int>(image.size() - 2));
        if (expected != actual) return fail_update(kind, "Update file CRC is invalid.");

        const char* state_error = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!connected_) state_error = "Connect to the WolfEye device first.";
            else if (update_active_) state_error = "A device update is already in progress.";
            else {
                update_active_ = true;
                update_kind_ = kind;
                update_image_ = std::move(image);
                update_crc_ = expected;
                update_offset_ = 0;
                update_part_size_ = 0;
                queue_.push_back(make_update_check(INTERNAL_UPDATE_CHECK_EXISTING));
            }
        }
        if (state_error) return fail_update(kind, state_error);
        emit(BE_PROVIDER_UPDATE_PROGRESS, kind, 0, nullptr, 0);
        return 0;
    }

private:
    void run() {
        bool unexpected_disconnect = false;
        while (true) {
            dispatch();
            SOCKET socket = INVALID_SOCKET;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (stop_requested_) break;
                socket = socket_;
            }
            if (socket == INVALID_SOCKET) break;

            fd_set readable;
            FD_ZERO(&readable);
            FD_SET(socket, &readable);
            timeval timeout{0, 100000};
            const int selected = select(0, &readable, nullptr, nullptr, &timeout);
            if (selected > 0) {
                uint8_t data[8192];
                const int count = recv(socket, reinterpret_cast<char*>(data), sizeof(data), 0);
                if (count <= 0) {
                    unexpected_disconnect = true;
                    break;
                }
                receive_buffer_.insert(receive_buffer_.end(), data, data + count);
                parse_frames();
            } else if (selected == SOCKET_ERROR) {
                const int error = WSAGetLastError();
                if (error != WSAEINTR) unexpected_disconnect = true;
                if (unexpected_disconnect) break;
            }
            check_timeout();
        }

        SOCKET socket = INVALID_SOCKET;
        bool notify = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            socket = socket_;
            socket_ = INVALID_SOCKET;
            notify = connected_ && unexpected_disconnect;
            connected_ = false;
            queue_.clear();
            pending_.reset();
            clear_update_locked();
        }
        if (socket != INVALID_SOCKET) closesocket(socket);
        if (notify) emit(BE_PROVIDER_DISCONNECTED, 0, 0, nullptr, 0);
    }

    void dispatch() {
        Request request{};
        uint8_t sequence = 0;
        SOCKET socket = INVALID_SOCKET;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            if (pending_ || queue_.empty() || !connected_) return;
            request = std::move(queue_.front());
            queue_.pop_front();
            sequence = sequence_++;
            if (!sequence_) sequence_ = 1;
            pending_ = Pending{
                request,
                sequence,
                std::chrono::steady_clock::now() + std::chrono::seconds(15),
            };
            socket = socket_;
        }

        std::vector<uint8_t> payload;
        payload.reserve(request.payload.size() + (legacy_protocol_ ? 0 : 1));
        if (!legacy_protocol_) payload.push_back(sequence);
        payload.insert(payload.end(), request.payload.begin(), request.payload.end());
        std::vector<uint8_t> frame(payload.size() + 7);
        const int frame_size = be_frame_build(
            request.frame_type, payload.data(), payload.size(), frame.data(), frame.size()
        );
        if (frame_size < 0 || !send_all(socket, frame.data(), static_cast<size_t>(frame_size))) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                pending_.reset();
            }
            emit_error(request.tag, "Native request send failed.");
        } else if (legacy_protocol_ && request.frame_type == 17) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                pending_.reset();
            }
            emit(BE_PROVIDER_RESPONSE, request.tag, request.frame_type, nullptr, 0);
        }
    }

    static bool send_all(SOCKET socket, const uint8_t* data, size_t size) {
        while (size) {
            const int sent = send(
                socket, reinterpret_cast<const char*>(data),
                static_cast<int>(std::min<size_t>(size, INT_MAX)), 0
            );
            if (sent <= 0) return false;
            data += sent;
            size -= static_cast<size_t>(sent);
        }
        return true;
    }

    void parse_frames() {
        while (true) {
            auto start = std::search(
                receive_buffer_.begin(), receive_buffer_.end(),
                std::begin(start_bytes_), std::end(start_bytes_)
            );
            if (start == receive_buffer_.end()) {
                if (!receive_buffer_.empty() && receive_buffer_.back() == start_bytes_[0]) {
                    receive_buffer_.assign(1, start_bytes_[0]);
                } else {
                    receive_buffer_.clear();
                }
                return;
            }
            receive_buffer_.erase(receive_buffer_.begin(), start);
            if (receive_buffer_.size() < 7) return;
            const size_t payload_size = receive_buffer_[2] |
                (static_cast<size_t>(receive_buffer_[3]) << 8);
            // The uint16 wire length bounds allocation to 65535 bytes. Event
            // replies can exceed the outgoing 5 KiB company workspace.
            const size_t total = payload_size + 7;
            if (receive_buffer_.size() < total) return;
            uint8_t frame_type = 0;
            std::vector<uint8_t> payload(std::max<size_t>(1, payload_size));
            const int decoded = be_frame_decode(
                receive_buffer_.data(), total, &frame_type, payload.data(), payload.size()
            );
            if (decoded < 0) {
                receive_buffer_.erase(receive_buffer_.begin());
                continue;
            }
            receive_buffer_.erase(receive_buffer_.begin(), receive_buffer_.begin() + total);
            if (decoded < 0 || (!legacy_protocol_ && decoded < 1)) continue;
            handle_response(frame_type, payload.data(), static_cast<size_t>(decoded));
        }
    }

    void handle_response(uint8_t frame_type, const uint8_t* payload, size_t size) {
        Request request{};
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!pending_ || (!legacy_protocol_ && pending_->sequence != payload[0])) return;
            request = std::move(pending_->request);
            pending_.reset();
        }
        const uint8_t* body = payload + (legacy_protocol_ ? 0 : 1);
        const size_t body_size = size - (legacy_protocol_ ? 0 : 1);
        if (request.tag >= INTERNAL_UPDATE_CHECK_EXISTING) {
            handle_update_response(request.tag, body, body_size);
        } else {
            emit(BE_PROVIDER_RESPONSE, request.tag, frame_type, body, body_size);
        }
    }

    void handle_update_response(uint32_t tag, const uint8_t* body, size_t size) {
        if (!size) {
            uint32_t kind = 0;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                kind = update_kind_;
                clear_update_locked();
            }
            const char* message = "Device returned an empty update status.";
            emit(BE_PROVIDER_UPDATE_FINISHED, kind, 0,
                 reinterpret_cast<const uint8_t*>(message), std::strlen(message));
            return;
        }
        const uint8_t status = body[0];
        uint32_t progress = UINT32_MAX;
        uint32_t kind = 0;
        bool finished = false;
        bool success = false;
        const char* message = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!update_active_) return;
            kind = update_kind_;
            if (tag == INTERNAL_UPDATE_CHECK_EXISTING) {
                if (status == STATUS_NO_NEED_UPLOAD) queue_.push_front(make_update_signal());
                else queue_.push_front(make_update_part());
            } else if (tag == INTERNAL_UPDATE_UPLOAD_PART) {
                if (status == STATUS_FILE_FRAME_UPLOAD_SUCCESS) {
                    update_offset_ += update_part_size_;
                    progress = update_image_.empty()
                        ? 0
                        : static_cast<uint32_t>(std::min<size_t>(100, update_offset_ * 100 / update_image_.size()));
                    queue_.push_front(update_offset_ >= update_image_.size()
                        ? make_update_check(INTERNAL_UPDATE_CHECK_UPLOADED)
                        : make_update_part());
                } else if (status == STATUS_FILE_WRITE_SUCCESS) {
                    update_offset_ = update_image_.size();
                    progress = 100;
                    queue_.push_front(make_update_check(INTERNAL_UPDATE_CHECK_UPLOADED));
                } else {
                    finished = true;
                    message = status == STATUS_FILE_WRITE_ERROR
                        ? "Device could not save the update file."
                        : "Device returned an unexpected upload status.";
                }
            } else if (tag == INTERNAL_UPDATE_CHECK_UPLOADED) {
                if (status == STATUS_NO_NEED_UPLOAD) queue_.push_front(make_update_signal());
                else {
                    finished = true;
                    message = "The uploaded file is damaged.";
                }
            } else if (tag == INTERNAL_UPDATE_SIGNAL) {
                finished = true;
                success = status == STATUS_RESETTING;
                message = success
                    ? "Update accepted. Reconnect after a few minutes."
                    : "Device returned an unexpected update status.";
            }
            if (finished) clear_update_locked();
        }
        if (progress != UINT32_MAX) {
            emit(BE_PROVIDER_UPDATE_PROGRESS, kind, progress, nullptr, 0);
        }
        if (finished) {
            emit(BE_PROVIDER_UPDATE_FINISHED, kind, success ? 1u : 0u,
                 reinterpret_cast<const uint8_t*>(message), std::strlen(message));
        }
    }

    Request make_update_check(uint32_t tag) const {
        const bool firmware = update_kind_ == BE_PROVIDER_FIRMWARE;
        return {
            tag,
            firmware ? FRAME_CHECK_UPDATE_FIRMWARE : FRAME_CHECK_UPDATE_BOOTLOADER,
            {static_cast<uint8_t>(update_crc_), static_cast<uint8_t>(update_crc_ >> 8)},
        };
    }

    Request make_update_part() {
        const size_t remaining = update_image_.size() - update_offset_;
        update_part_size_ = std::min(FILE_CHUNK_SIZE, remaining);
        uint8_t flags = update_offset_ == 0 ? FILE_FLAG_FIRST_PART : 0;
        if (update_part_size_ == remaining) flags |= FILE_FLAG_LAST_PART;
        std::vector<uint8_t> payload;
        payload.reserve(update_part_size_ + 1);
        payload.push_back(flags);
        payload.insert(
            payload.end(), update_image_.begin() + update_offset_,
            update_image_.begin() + update_offset_ + update_part_size_
        );
        return {
            INTERNAL_UPDATE_UPLOAD_PART,
            update_kind_ == BE_PROVIDER_FIRMWARE ? FRAME_FILE_FIRMWARE : FRAME_FILE_BOOTLOADER,
            std::move(payload),
        };
    }

    Request make_update_signal() const {
        return {
            INTERNAL_UPDATE_SIGNAL,
            update_kind_ == BE_PROVIDER_FIRMWARE
                ? FRAME_UPDATE_FIRMWARE_SIGNAL
                : FRAME_UPDATE_BOOTLOADER_SIGNAL,
            {},
        };
    }

    void check_timeout() {
        uint32_t tag = 0;
        uint32_t update_kind = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!pending_ || std::chrono::steady_clock::now() < pending_->deadline) return;
            tag = pending_->request.tag;
            pending_.reset();
            if (tag >= INTERNAL_UPDATE_CHECK_EXISTING) {
                update_kind = update_kind_;
                clear_update_locked();
            }
        }
        if (update_kind) {
            const char* message = "WolfEye update request timed out.";
            emit(BE_PROVIDER_UPDATE_FINISHED, update_kind, 0,
                 reinterpret_cast<const uint8_t*>(message), std::strlen(message));
            return;
        }
        emit(BE_PROVIDER_TIMEOUT, tag, 0, nullptr, 0);
    }

    int fail(const char* message) {
        emit_error(0, message);
        return -1;
    }

    int fail_update(uint32_t kind, const char* message) {
        emit(BE_PROVIDER_UPDATE_FINISHED, kind, 0,
             reinterpret_cast<const uint8_t*>(message), std::strlen(message));
        return -1;
    }

    void emit_error(uint32_t tag, const char* message) {
        emit(BE_PROVIDER_ERROR, tag, 0,
             reinterpret_cast<const uint8_t*>(message), std::strlen(message));
    }

    void clear_update_locked() {
        update_active_ = false;
        update_kind_ = 0;
        update_image_.clear();
        update_crc_ = 0;
        update_offset_ = 0;
        update_part_size_ = 0;
    }

    void emit(
        uint32_t event, uint32_t tag, uint32_t value,
        const uint8_t* data, size_t size
    ) const {
        if (callback_) callback_(context_, event, tag, value, data, size);
    }

    void join_worker() {
        if (worker_.joinable() && worker_.get_id() != std::this_thread::get_id()) worker_.join();
    }

    BEProviderCallback callback_ = nullptr;
    void* context_ = nullptr;
    mutable std::mutex mutex_;
    std::thread worker_;
    SOCKET socket_ = INVALID_SOCKET;
    bool stop_requested_ = false;
    bool connected_ = false;
    bool legacy_protocol_ = false;
    uint8_t sequence_ = 1;
    std::deque<Request> queue_;
    std::optional<Pending> pending_;
    std::vector<uint8_t> receive_buffer_;
    const uint8_t start_bytes_[2] = {0x41, 0x24};

    bool update_active_ = false;
    uint32_t update_kind_ = 0;
    std::vector<uint8_t> update_image_;
    uint16_t update_crc_ = 0;
    size_t update_offset_ = 0;
    size_t update_part_size_ = 0;
};
}

void* __cdecl be_provider_create(BEProviderCallback callback, void* context) {
    try {
        return new Provider(callback, context);
    } catch (...) {
        return nullptr;
    }
}

void __cdecl be_provider_destroy(void* provider) {
    delete static_cast<Provider*>(provider);
}

int __cdecl be_provider_start(
    void* provider, const char* ip, uint16_t port, uint32_t timeout_ms, uint32_t legacy_protocol
) {
    try {
        return provider
            ? static_cast<Provider*>(provider)->start(ip, port, timeout_ms, legacy_protocol != 0)
            : -1;
    } catch (...) {
        return -1;
    }
}

void __cdecl be_provider_stop(void* provider) {
    if (provider) static_cast<Provider*>(provider)->stop();
}

int __cdecl be_provider_request(
    void* provider, uint32_t tag, uint8_t frame_type,
    const uint8_t* payload, size_t payload_size
) {
    try {
        return provider
            ? static_cast<Provider*>(provider)->request(tag, frame_type, payload, payload_size)
            : -1;
    } catch (...) {
        return -1;
    }
}

int __cdecl be_provider_update_file(
    void* provider, uint32_t kind, const wchar_t* path,
    uint32_t device_hardware, uint32_t device_bootloader
) {
    try {
        return provider
            ? static_cast<Provider*>(provider)->update_file(
                kind, path, device_hardware, device_bootloader
            )
            : -1;
    } catch (...) {
        return -1;
    }
}
