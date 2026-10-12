
// DO NOT move this two lines
#ifdef _WIN32
#include <malloc.h>
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#endif
#include "asio/include/asio.hpp"

#include "DataProvider.h"

#include <chrono>
#include <fstream>
#include <filesystem>

#include <ser4cpp/container/WSeq.h>
#include <ser4cpp/container/SequenceTypes.h>
#include <ser4cpp/serialization/LittleEndian.h>

#include <ctime>
#include <cstring>

#define TIMESTAMP_TO_STRING(time, str, size) do{ \
	time_t rawtime = time/1000; \
	struct tm timeinfo; \
	localtime_s(&timeinfo, &rawtime); \
	strftime(str,size,"%y/%m/%d %H:%M:%S", &timeinfo); \
}while(0);


#define sprintf(...) sprintf_s(__VA_ARGS__)

#define PASS_FRAME	&frame.buffer[1], frame.length-1

#define MSG(msg)  Log(msg)
#define MSG_F(...) do{ \
	char msg[128]; \
	sprintf_s(msg, __VA_ARGS__); \
	MSG(msg); \
}while (0);
#define LOG(d, ...) do{ \
	char msg[512]; \
	sprintf_s(msg, __VA_ARGS__); \
	std::cout << msg << "\n" << std::flush; \
}while (0)
#define msgv_addlog(d,...) MSG_F(__VA_ARGS__)


#define USED_BUFFERD_FILE		1

#define UPLOAD_FILE_EXIST		1
#define UPLOAD_FILE_CHECKING	2
//#define UPLOAD_FILE_SAVING		2

#define FILE_FLAG_FIRST_PART		(0x01)
#define FILE_FLAG_LAST_PART			(0x02)
#define FILE_FLAG_SINGL_PART		(FILE_FLAG_LAST_PART | FILE_FLAG_FIRST_PART)

#define RESPONSE_WAIT_INTERVAL		(10000)

#define SET_AR_MODE(mode, m1, m2, m3, m4) do{ \
	mode[0] = m1; \
    mode[1] = m2; \
    mode[2] = m3; \
    mode[3] = m4; \
}while(0);

#define DEFAULT_GROUP_OPTIONS(tcc) do{ \
	tcc.MIN = 1; \
	tcc.TM = 1; \
	tcc.Ta = 0; \
	tcc.Tmax = 120000; \
	tcc.Tmin = 0; \
	tcc.max_mode = 0; \
}while(0);

using asio::ip::icmp;
using asio::steady_timer;
using asio::ip::tcp;

struct DataProvider::ASIOImpl
{
	asio::io_context context;
	tcp::socket socket;

	ASIOImpl() : socket(context) {}
};

DataProvider::DataProvider(data_cb_t d_cb, log_cb_t l_cb)
	:
	settings(std::make_shared<Settings>()), bi(std::make_shared<BIs>()), ai(std::make_shared<AIs>(settings)),
	is_connected(false), DataCB(d_cb), LogCB(l_cb),
	asioImpl(std::make_unique<ASIOImpl>())
{
	crcInit();
	sprintf_s(dev.ip, DEFAULT_IP);
	dev.port = 80;
	dev.build = 50;

	ReloadPoints();

	LoadDefault();
}

DataProvider::~DataProvider() = default;

void DataProvider::Start(const char* ip, uint16_t port)
{
	strcpy_s(dev.ip, ip);
	dev.port = port;

	if(!lstream)
	{
		lstream = std::make_shared<LightStream>(std::shared_ptr<IFrame>(this));
		LOG(LOG_DEBUG, "lstream created");
	}
	else
	{
		LOG(LOG_DEBUG, "lstream created before not need to create");
	}

	LOG(LOG_DEBUG, "thread starting");
	
	kill_thread = false;
	is_thread_running = false;
	t = std::thread([=]() {

		uint64_t c = 0;
		while (!kill_thread)
		{
			is_thread_running = true;
			asioImpl->context.run();

			std::this_thread::sleep_for(std::chrono::milliseconds(10));
			
			// try to connect
			if (!is_connected)
			{
				if (kill_thread)
					break;

				Connect();
				if (!is_connected)
				{
					is_thread_running = false;
					break;
				}
			}
			else
			{
				if (WaitToResponse())
					continue;
				else if (command == Command::GET_INFO)
					Info();
				else if (command == Command::GET_SETTINGS)
					ReadConfig();
				else if (command == Command::SAVE_SETTING)
					UpdateConfig();
				else if (command == Command::RESET)
					ResetDevice();
				else if (command == Command::GET_MEASUREMENT)
					UpdateStatus();
				else if (command == Command::GET_EVENTS)
					GetEvents();
				else if (command == Command::GET_SIGNAL)
					GetSignal();
				else if (command == Command::UPDATE)
					UpdateProgress();
				else if (command == Command::UPLOAD)
					UploadProgress();

				//else if (command == Command::DOWNLOAD)
				//	DownloadProgress();
				//else if (dev.is_info_loaded && !dev.is_setting_loaded)
				//	ReadConfig();
			}

			c++;
		}

		LOG(LOG_DEBUG, "thread terminated");
		is_thread_running = false;
	});
	t.detach();
}

void DataProvider::Do(Command cmd)
{
	command = cmd;
}

void DataProvider::Do(Command cmd, request_cb_t& callback)
{
	command = cmd;
	ReqCB = callback;
	is_set_callback = true;
}

void DataProvider::CommandExecuted(bool success)
{
	if (success && is_set_callback)
		ReqCB();

	command = Command::IDLE;
	is_set_callback = false;
}

bool DataProvider::IsCommandIDLE()
{
	return command == Command::IDLE;
}

void DataProvider::Stop()
{
	kill_thread = true;
	LOG(LOG_DEBUG, "request to kill thread");

	if (asioImpl->socket.is_open())
	{
		asio::error_code ec;
		asioImpl->socket.shutdown(asio::ip::tcp::socket::shutdown_both, ec);
		asioImpl->socket.close();
		//context.stop();
	}
	CommandExecuted(false);
	is_connected = false;
	PassInfoToUI();
	MSG("Disconnected!");
}

void DataProvider::UpdateStatus()
{
	MSG("Reading status...");

	/* [req_types(1)
	*  req_types:M_TYPE_1 | M_TYPE_2 ...
		*/
	lstream->InitFrame();
	lstream->FrameHeader(FrameType::MEASUREMENTS, 2);
	lstream->PushDataToFrame(&sequence, 1);
	uint8_t m = M_TYPE_BI | M_TYPE_AI;
	lstream->PushDataToFrame(&m, 1);
	Send(lstream->Frame());
}

void DataProvider::Info()
{
	if (dev.is_info_loaded)
	{
		CommandExecuted();
		return;
	}

	Request(FrameType::INFO);
	MSG("Loading device info...");

}

void DataProvider::Connect()
{
	// connect to EmWolf
	if (dev.port == EMWOLF_PORT) 
	{
		// if Ping reply get under 10ms we take connection as local
		if (ICMPPing(dev.ip, 10, false))
			EWConnect();
		else
			MSG_F("The %s host not found", dev.ip);
		return;
	}

	// we need to load device info/settings at every connect
	dev.is_info_loaded = false;
	dev.is_setting_loaded = false;

	MSG_F("Connecting to %s", dev.ip);
 
	try
	{
#if 0
		// if we connecting through wifi
		if (!strncmp(dev.ip, "192.168.4.1", strlen("192.168.4.1")))
			is_tcp_supported = true;
		// if Ping reply get under 10ms we take connection as local
		else if (ICMPPing(dev.ip, 10, false))
			Info();
		else
			is_tcp_supported = true;

		if (is_tcp_supported)
#endif
		{
			// TODO: use error_code to check errors
			// socket.wait will wait till there is some data to read
			//LOG(LOG_DEBUG, "tcp connection supported");
			tcp::resolver resolver(asioImpl->context);
			auto query = tcp::resolver::query(tcp::v4(), host, std::to_string(TCP_PORT));
			asio::connect(asioImpl->socket, resolver.resolve(query));
			is_connected = asioImpl->socket.is_open();
		}

		if (is_connected)
		{
			MSG("Connected!");
			ReadAsync();
			Do(Command::GET_INFO);
		}
		else
		{
			MSG("Timeout!");
			is_timeout = true;
			PassInfoToUI();
		}
	}
	catch (...)
	{

	}
	
}

void DataProvider::ReadAsync()
{
	try {
		asioImpl->socket.async_read_some(asio::buffer(lstream->ReadBuffer(), lstream->Size()),
			[&](std::error_code ec, size_t nread)
			{
				if (!ec)
				{
					//for (int i = 0; i < nread; i++)
					//    std::cout << std::hex << (int)lstream->ReadBuffer()[i] << " ";
					LOG(LOG_DEBUG, "%i bytes received!", nread);
					lstream->Check(nread);
					ReadAsync();
				}
			});
	}
	catch (std::exception& e) {
		std::cerr << "Exception: " << e.what() << std::endl;
	}
}

void DataProvider::Send(LSBuff * frame)
{
	Wait();

	size_t nwrite = asio::write(asioImpl->socket, asio::buffer(frame->Buffer(), frame->Used()));
	//LOG(LOG_DEBUG, "size(%i) sent(%i)", frame->Size(), nwrite);

	// all data sent
	if (nwrite == frame->Used())
	{
		response_timer.Reset();
	}
}

void DataProvider::Request(FrameType type)
{
	respose_status = Status::INVALID;
	lstream->InitFrame();
	lstream->FrameHeader(type, 1);
	lstream->PushDataToFrame(&sequence, 1);
	Send(lstream->Frame());
}

void DataProvider::UpdateConfig()
{
	MSG("Settings Writing...");

	settings->PrepareLists(&settings->config, dev.type == DeviceType::AUTO_RECLOSER);
	lstream->InitFrame();
	lstream->FrameHeader(FrameType::SAVE_SETTINGS);
	lstream->PushDataToFrame(&sequence, 1);
	settings->Serialize(lstream->WriteBuffer().End());
	lstream->WriteBuffer().Advance(settings->SerializeSize());
	Send(lstream->Frame());
}

void DataProvider::ReadConfig()
{
	Request(FrameType::GET_SETTINGS);
	MSG("Reading settings...");
}

void DataProvider::OnFrame(SFrame& frame)
{
	LOG(LOG_DEBUG, "received status(%i) type(%i) length(%i) command(%i)", (int)frame.status, 
		(int)frame.type, frame.length, (int)command);
	
	if (frame.status == FrameStatus::CRC_ERROR)
	{
		MSG("CRC Error!");
		waiting_for_response = false;
		return;
	}

	// check sequence
	if (frame.buffer[0] != sequence)
	{
		LOG(LOG_DEBUG, "Unexpected Sequence. %d %d", sequence, frame.buffer[0]);
		return;
	}

	// TODO this feature not working
	// check if the remote device get the frame with CRC-ERORR
	//if (frame.type == FrameType::RESPONSE && ((Status)frame.buffer[1]) == Status::CRC_ERROR)
	//{
	//	LOG(LOG_DEBUG, "CRC Error, Need To send again.");
	//}

	sequence++;
	if (sequence == 0)
		sequence = 1;

	switch (command)
	{
	case Command::GET_INFO:
		InfoDeserialize(PASS_FRAME);
		break;
	case Command::GET_MEASUREMENT:
		MeasurementDeserialize(PASS_FRAME);
		break;
	case Command::GET_SETTINGS:
		SettingsDeserialize(PASS_FRAME);
		break;
	case Command::SAVE_SETTING:
		if ((Status)frame.buffer[1] == Status::NO_NEED_UPLOAD)
			MSG("Same Settings. No Need to Save.");
		else
			MSG("New Settings Applied.");

		CommandExecuted();
		break;
	case Command::GET_EVENTS:
		EventsDeserialize(PASS_FRAME);
		break;
	case Command::GET_SIGNAL:
	{
		memcpy(signal.buffer, &frame.buffer[1], frame.length-1);
		CommandExecuted();
		break;
	}
	case Command::RESET:
		// after reset need to disconnect
		Stop();
		MSG("RESET! you need to connect again.");
		break;
	case Command::UPDATE:
	{
		Status status = (Status)frame.buffer[1];
		if (status == Status::RESETTING)
		{
			Stop();
			MSG("Device going to Update mode. You can connect after a few minutes!");
		}
		break;
	}
	case Command::UPLOAD:
	{
		Status status = (Status)frame.buffer[1];

		// we checking if file exist before uploading
		if (file_transfer_checking_step == UPLOAD_FILE_EXIST || file_transfer_checking_step == UPLOAD_FILE_CHECKING)
		{
			if (status == Status::NO_NEED_UPLOAD)
			{
				if (file_transfer_checking_step == UPLOAD_FILE_EXIST)
					Log( "File Already Uploaded");
				else
					Log("File Checked Successfully!");

				FileTransferFinished();

				// what we need after uploading file
				if (after_upload == AfterUpload::UPDATE)
					Do(Command::UPDATE);

			}
			else if (file_transfer_checking_step == UPLOAD_FILE_CHECKING)
			{
				Log("The Uploaded File Is Damaged!");
				FileTransferFinished();
			}
			else
			{
				// we need to upload file anyway!
				file_transfer_checking_step = 0;
			}
		}
		else
		{
			if (status == Status::FILE_FRAME_UPLOAD_SUCCESS)
			{
				LOG(LOG_DEBUG, "file frame send successfully!");
				file_index += file_partion_size;
			}
			else if (status == Status::FILE_WRITE_SUCCESS)
			{
				Log("File Uploaded Successfully");
				PassProgressToUI(1000);
				file_transfer_checking_step = UPLOAD_FILE_CHECKING;
			}
			else if (status == Status::FILE_WRITE_ERROR)
			{
				Log("File Save Failed!");
				CommandExecuted();
			}
		}
		break;
	}
	}

#if 0
	switch (frame.type)
	{
	case FrameType::STATUS:
	{
		/* [type(1)] [status(1)]
		*/
		Status status = (Status)frame.buffer[1];
		switch ((FrameType)frame.buffer[0])
		{
		case FrameType::SAVE_FILE:
			if (frame.buffer[1])
			{
				if((Status)frame.buffer[2] == Status::OK)
				{
				}
			}
			else
			{
				LOG(LOG_DEBUG, "device storage error(%i)", frame.buffer[2]);
				MSG("Storage Error!");
				FileTransferFinished();
			}
			break;
		case FrameType::UPLOAD:
			// is frame error
			if (frame.buffer[1])
			{
				switch ((Status)frame.buffer[2])
				{
				case Status::OK:
					file_header[1]++;
					retry_counter = 0;
					break;
				case Status::CRC_ERROR:
					retry_counter++;
					break;
				default:
					break;
				}
			}
			else
			{
				LOG(LOG_DEBUG, "device storage error(%i)", frame.buffer[2]);
				MSG("Storage Error!");
				FileTransferFinished();
			}
			break;
		case FrameType::UPDATE:
			if (frame.buffer[1] == (uint8_t)Status::OK)
			{
				MSG("Sent!");
				MSG("The device going to reset, please wait until we get result after reset.");
			}
			else
			{
				MSG("Update failed");
			}
			break;
		case FrameType::CHECK:
			respose_status = (Status)frame.buffer[1];
			if (respose_status == Status::FILE_SIZE)
			{
				file_size = *((size_t*)&frame.buffer[2]);
			}
			break;
		case FrameType::STATUS:
			// the frame we sent, received by remote with CRC_ERROR, should we send it again?!
			if (status == Status::CRC_ERROR)
			{

			}
			break;
		default:
			break;
		}
		break;
	}
	case FrameType::FILE:
	{
		/* [file_sequence(2)] [data<...>]
		*/
		uint16_t sequence = *((uint16_t*)frame.buffer);
		if (sequence != this->sequence) // wrong sequence
		{
			LOG(LOG_DEBUG, "wrong sequence");
			return;
		}

		memcpy(file + file_index, &frame.buffer[2], frame.length - 2);
		this->sequence++;
		file_index += frame.length - 2;
		retry_counter = 0;
		LOG(LOG_DEBUG, "sequence(%u) downloaded", sequence);
		break;
	}
	default:
		break;
	}
#endif
	waiting_for_response = false;
}

void DataProvider::ResetDevice()
{
	Request(FrameType::RESET);
	MSG("Reset Requested");
}

void DataProvider::Wait()
{
	waiting_for_response = true;
	response_timer.Reset();
}

uint8_t DataProvider::Timeout(int seconds)
{
	if (!waiting_for_response)
		return RES_TIMER_NOT_WAIT;
	
	if (response_timer.Interval(utils::TimeUnit::SECOND) >= seconds)
	{
		waiting_for_response = false;
		return RES_TIMER_TIMEOUT;
	}

	return RES_TIMER_WAIT;
}

bool DataProvider::WaitToResponse()
{
	uint8_t t = Timeout(15);
	if (t != RES_TIMER_NOT_WAIT)
	{
		if (t == RES_TIMER_TIMEOUT)
		{
			MSG("Timeout!");
			CommandExecuted(false);
			is_timeout = true;
			PassInfoToUI();
		}

		return true;
	}

	return false;
}

bool DataProvider::ICMPPing(std::string ip, uint32_t timeout, bool do_log)
{
	bool status = false;
	try {
		asio::io_context io;

		icmp::resolver resolver(io);
		auto endpoints = resolver.resolve(icmp::v4(), ip, "");

		icmp::endpoint destination = *endpoints.begin();

		// Create ICMP socket
		icmp::socket socket(io, icmp::v4());

		// Create ICMP echo request packet
		std::array<unsigned char, 8> echo_request{};
		echo_request[0] = 8; // Type: Echo Request
		echo_request[1] = 0; // Code: 0

		// Calculate checksum
		uint16_t checksum = 0;
		for (size_t i = 0; i < echo_request.size(); i += 2) {
			checksum += (echo_request[i] << 8) + echo_request[i + 1];
		}
		checksum = (checksum >> 16) + (checksum & 0xFFFF);
		checksum = ~checksum;

		echo_request[2] = (checksum >> 8) & 0xFF;
		echo_request[3] = checksum & 0xFF;

		// Send the echo request
		socket.send_to(asio::buffer(echo_request), destination);

		std::array<char, 1024> reply_buf;
		icmp::endpoint sender;

		// Set receive timeout (optional)
		socket.non_blocking(true);
		auto start = std::chrono::steady_clock::now();

		while (true) {
			asio::error_code ec;
			size_t len = socket.receive_from(asio::buffer(reply_buf), sender, 0, ec);

			if (!ec && len > 0) 
			{
				if (do_log)
				{
					uint32_t elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
					if(elapsed == 0)
					{
						MSG("Get replay in <1ms");
					}
					else
					{
						MSG_F("Get replay in %ims", elapsed);
					}
				}
				status = true;
				break;
			}

			if (std::chrono::steady_clock::now() - start > std::chrono::milliseconds(timeout)) {
				if (do_log)
					MSG("Ping timed out.");
				break;
			}
		}

	}
	catch (std::exception& e) {
		std::cerr << "Exception: " << e.what() << std::endl;
	}

	return status;
}

void DataProvider::Log(const char* msg)
{
	LogCB(std::string(msg));
}

bool DataProvider::PassMeasurementToUI()
{
	// M -> {id, name, val, dnp}
	cJSON* root = cJSON_CreateObject();

	cJSON* binaries = cJSON_CreateArray();
	cJSON_AddItemToObject(root, "b", binaries);

	cJSON* analogs = cJSON_CreateArray();
	cJSON_AddItemToObject(root, "a", analogs);

	// Binaries
	for (int i = 0; i < bi->list.size(); i++)
	{
		if (!bi->list[i].IsEnabled())
			continue;

		cJSON_AddItemToArray(binaries, 
			MeasurementItem(bi->list[i].Name(), (bool)bi->list[i], i, bi->list[i].dnp3.index));
	}

	// Analogs
	for (int i = 0; i < ai->list.size(); i++)
	{
		if (!ai->list[i].IsEnabled())
			continue;

		cJSON_AddItemToArray(analogs,
			MeasurementItem(ai->list[i].Name(), (uint16_t)ai->list[i], i, ai->list[i].dnp3.index));
	}

	// Pass to UI
	char* json = cJSON_PrintBuffered(root, SIZE_OF_JSON_STRING, 0);
	cJSON_Delete(root);
	DataCB(DataType::MEASUREMENTS, std::string(json));
	LOG(LOG_DEBUG, "Pass Measurements to UI");
	free(json);

	return true;
}

void DataProvider::PassInfoToUI(cJSON* root)
{
	if (!root)
		root = cJSON_CreateObject();

	cJSON* channel = cJSON_CreateString(is_timeout ? "timeout" : is_connected ? "connected" : "disconnected");
	is_timeout = false;
	cJSON_AddItemToObject(root, "channel", channel);
	char* json = cJSON_PrintBuffered(root, 128, 0);
	cJSON_Delete(root);
	root = nullptr;
	DataCB(DataType::INFO, std::string(json));
	LOG(LOG_DEBUG, "Pass Info to UI");
	free(json);
}

void DataProvider::PassConfigToUI()
{
	char* json = setting_to_json(&settings->config);
	DataCB(DataType::CONFIG, std::string(json));
	LOG(LOG_DEBUG, "Pass Configs to UI");
	free(json);
}

void DataProvider::PassEventsToUI()
{
	cJSON* root = cJSON_CreateObject();

	cJSON* evts = cJSON_CreateArray();
	cJSON_AddItemToObject(root, "e", evts);

	char str[64];

	for (int i = 0; i < events.Size(); i++)
	{
		EventToString(i, str, 64);

		cJSON* item = cJSON_CreateString(str);
		cJSON_AddItemToArray(evts, item);
	}

	char* json = cJSON_PrintBuffered(root, SIZE_OF_JSON_STRING, 0);
	cJSON_Delete(root);
	DataCB(DataType::EVENTS, std::string(json));
	LOG(LOG_DEBUG, "Pass Events to UI");
	free(json);
}

void DataProvider::LoadSetting(std::string path)
{
	std::ifstream stream;
	if (std::filesystem::exists(path))
	{
		stream.open(path, std::ios::binary);
		stream.read((char*)&settings->config, sizeof(Configure));
		stream.close();
		Log("Config file loaded");
		PassConfigToUI();
	}
}

void DataProvider::LoadSetting()
{
	Do(Command::GET_SETTINGS);
}

void DataProvider::SaveSettings(std::string json, std::string path)
{
	std::ofstream stream(path, std::ios::binary);

	if (!stream)
	{
		Log("Can't open file");
	}
	else
	{
		json_to_setting(json.c_str(), settings);

		uint16_t crc = crcFast((uint8_t*)&settings->config, sizeof(settings->config));
		stream.write((const char*)&settings->config, sizeof(settings->config));
		stream.write((const char*)&crc, 2);
		stream.close();
		Log("File saved!");
	}
}

void DataProvider::SaveSettingsToFile(std::string path)
{
	std::ofstream stream(path, std::ios::binary);

	if (!stream)
	{
		Log("Can't open file");
	}
	else
	{
		settings->PrepareLists(&settings->config, dev.type == DeviceType::AUTO_RECLOSER);
		// we add 1 byte as config file info and 2 bytes for crc
		uint8_t* buffer = new uint8_t[settings->SerializeSize() + 1];
		settings->Serialize(buffer);
		ser4cpp::wseq_t wseq(buffer + settings->SerializeSize(), 3);
		
		uint8_t flags = dev.type == DeviceType::AUTO_RECLOSER ? 1 : 0;
		ser4cpp::UInt8::write_to(wseq, flags);
		
		uint16_t crc = crcFast(buffer, settings->SerializeSize() + 1);

		stream.write((const char*)buffer, settings->SerializeSize() + 1);
		stream.write((const char*)&crc, 2);

		stream.close();
		Log("File saved!");
	}
}

void DataProvider::SaveSettings(std::string json)
{
	json_to_setting(json.c_str(), settings);
	Do(Command::SAVE_SETTING);
}

void DataProvider::DeviceTypeChanged(DeviceType type)
{
	dev.type = type;
	ReloadPoints();
	PassConfigToUI();
	PassMeasurementToUI();
}

void DataProvider::InfoDeserialize(uint8_t* buffer, size_t length)
{
	uint8_t model;
	uint16_t flags;

	ser4cpp::rseq_t rseq(buffer, length);
	ser4cpp::UInt8::read_from(rseq, model);
	sprintf(dev.model, model == 1 ? "FC22AR" : model == 2 ? "FC22S" : "");
	
	auto old_type = dev.type;
	dev.type = model == 1 ? DeviceType::AUTO_RECLOSER : DeviceType::SECIONALIZER;

	if (old_type != dev.type)
	{
		ReloadPoints();
		settings->Default(dev.type == DeviceType::AUTO_RECLOSER);
	}

	ser4cpp::UInt8::read_from(rseq, dev.firmware);
	ser4cpp::UInt8::read_from(rseq, dev.hardware);
	ser4cpp::UInt8::read_from(rseq, dev.bootloader);

	ser4cpp::UInt16::read_from(rseq, dev.build);
	ser4cpp::UInt16::read_from(rseq, flags);

	for (uint8_t i = 0; i < 8; i++)
		ser4cpp::UInt8::read_from(rseq, ((uint8_t*)dev.commit)[i]);

	cJSON* root = cJSON_CreateObject();

	cJSON_AddItemToObject(root, "model", cJSON_CreateString(dev.model));
	cJSON_AddItemToObject(root, "firmware", cJSON_CreateNumber(dev.firmware));
	cJSON_AddItemToObject(root, "hardware", cJSON_CreateNumber(dev.hardware));
	cJSON_AddItemToObject(root, "revision", cJSON_CreateNumber(dev.build));
	
	PassInfoToUI(root);

	if (!dev.is_setting_loaded)
		Do(Command::GET_SETTINGS);
	else
		CommandExecuted();
}

void DataProvider::MeasurementDeserialize(uint8_t* buffer, size_t length)
{
	// reload points every time we read measurements
	ReloadPoints();

	ser4cpp::rseq_t rseq(buffer, length);

	uint16_t index = 0;
	do
	{
		uint16_t header = 0;
		ser4cpp::UInt16::read_from(rseq, header);
		//index += 2;

		uint8_t type = (uint8_t)header & 0x0F;
		uint16_t count = header >> 4;

		if (type == M_TYPE_BI)
		{
			bi->Deserialize(rseq);
			rseq.advance(bi->SerializeSize());
		}
		else if (type == M_TYPE_AI)
		{
			ai->Deserialize(rseq);
			rseq.advance(ai->SerializeSize());
		}
		else if (type == M_TYPE_BC)
		{
		}

		if (rseq.is_empty())
			break;
	} while (1);

	MSG("Status loaded");
	CommandExecuted();

	PassMeasurementToUI();
}

void DataProvider::SettingsDeserialize(uint8_t* buffer, size_t length)
{
	settings->PrepareLists(&settings->config, dev.type == DeviceType::AUTO_RECLOSER);
	settings->Deserialize(buffer);
	MSG("Settings loaded");
	CommandExecuted();
	PassConfigToUI();
}

void DataProvider::EventsDeserialize(uint8_t* buffer, size_t length)
{
	MSG("Events loaded");
	size_t offset = 0;
	events.Reset();
	while (offset + 8 < length)
	{
		Event e;
		e.Deserialize(buffer + offset);
		offset += e.SerializeSize();
		events.AddToList(e);
	}
	CommandExecuted();

	PassEventsToUI();
}

void DataProvider::ReloadPoints()
{
	for (uint16_t i = 0; i < bi->list.size(); i++)
		bi->list[i].Enable();

	for (uint16_t i = 0; i < ai->list.size(); i++)
		ai->list[i].Enable();

	if (dev.type == DeviceType::AUTO_RECLOSER)
	{
		bi->DisablePoints(true, dev.build);
		ai->DisablePoints(true, dev.build);
	}
	else
	{
		bi->DisablePoints(false, dev.build);
		ai->DisablePoints(false, dev.build);
	}

	// sort according to DNP ID
	bi_list.clear();
	ai_list.clear();

	for (const auto& itm : bi->list)
		bi_list.push_back(&itm);
	for (const auto& itm : ai->list)
		ai_list.push_back(&itm);

	std::sort(bi_list.begin(), bi_list.end(),
		[](const BI* a, const BI* b)
		{
			return a->dnp3.index < b->dnp3.index;
		});
	std::sort(ai_list.begin(), ai_list.end(),
		[](const AI* a, const AI* b)
		{
			return a->dnp3.index < b->dnp3.index;
		});
}

void DataProvider::LoadDefault()
{
	settings->Default(dev.type == DeviceType::AUTO_RECLOSER);
	PassConfigToUI();
}

void DataProvider::GetEvents()
{
	MSG("Reading Last Events ...");
	Request(FrameType::EVENTS);
}

void DataProvider::GetSignal()
{
	Request(FrameType::SIGNAL);
}

void DataProvider::EventToString(uint16_t index, char* str, size_t size)
{
	auto e = events.Get(index);

	char dt[18];
	const char* name = "";
	uint16_t byte_count = 0;

	TIMESTAMP_TO_STRING((e.Time() - 12600000), dt, 18);
	switch (e.Type())
	{
	case EventLogType::BI:
		name = bi->list[e.Position()].Name();
		break;
	case EventLogType::AI:
		name = ai->list[e.Position()].Name();
		break;
	}
	int milli = e.Time() % 1000;

	std::snprintf(str, size, "%04i: %s.%03i %5lu %s", index, dt, milli, e.Value(), name);
}

void DataProvider::Update(UpdateType type, std::string path)
{
	if (dev.bootloader < 2)
	{
		MSG("Not Supported By Device!");
		return;
	}

	std::ifstream stream;
	if (std::filesystem::exists(path))
	{
		file_type = type == UpdateType::FIRMWARE ? FrameType::FILE_FIRMWARE : FrameType::FILE_BOOTLOADER;
		file_size = std::filesystem::file_size(path);
		file = new uint8_t[file_size];
		memset(file, 0xff, file_size);
		file_index = 0;

		stream.open(path, std::ios::binary);
		stream.read((char*)file, file_size);
		stream.close();
		LOG(LOG_DEBUG, "%s file read(%i)", path.c_str(), file_size);
		
		// check file
		const char* token_dfhb = "DFHB-VER";
		char dfhb[64];
		uint8_t c = 0;
		for (uint32_t i = 0; i < file_size; i++)
		{
			if (file[i] == token_dfhb[c])
			{
				c++;
				if (c == strlen(token_dfhb))
				{
					strncpy_s(dfhb, (char*)&file[i + 2], 64);
					LOG(LOG_DEBUG, dfhb);
					break;
				}
			}
			else
				c = 0;
		}

		// can't fine dfhb version, so file invalid
		if (c == 0)
		{
			MSG("Invalid File!");
			UpdateFinished(true);
			return;
		}

		// check version
		char device[10], commit[10];
		uint8_t firmware = 0, hardware = 0, revision = 0;
		//char* model = 0;
		uint16_t frm_ver = 0, hrd_ver = 0;
		char* context = nullptr;
		char* token = strtok_s((char*)dfhb, ".", &context);
		c = 0;
		while (token != NULL)
		{
			if (c == 0)
				strcpy_s(device, token);
			else if (c == 1)
				firmware = (int)strtol(token, (char**)NULL, 10);
			else if (c == 2)
				hardware = (int)strtol(token, (char**)NULL, 10);
			else if (c == 3)
				revision = (int)strtol(token, (char**)NULL, 10);
			else if (c == 4)
			{
				strcpy_s(commit, token);
				break;
			}

			c++;
			token = strtok_s(NULL, ".", &context);
		}
		if (dev.hardware != hardware)
		{
			MSG(dfhb);
			MSG("File Not Compatible With The Device!");
			UpdateFinished(true);
			return;
		}

		// check crc
		file_crc = *((uint16_t*)&file[file_size - 2]);
		uint16_t crc_cal = crcFast(file, file_size - 2);
		if (file_crc != crc_cal)
		{
			MSG("Invalid File!");
			UpdateFinished(true);
			return;
		}

		after_upload = AfterUpload::UPDATE;
		Upload();
	}
	else
	{
		MSG("File Not Found!");
	}
}

void DataProvider::UpdateProgress()
{
	lstream->InitFrame();
	lstream->FrameHeader(file_type == FrameType::FILE_FIRMWARE ? FrameType::UPDATE_FIRMWARE_SIGNAL : FrameType::UPDATE_BOOTLOADER_SIGNAL);
	lstream->PushDataToFrame(&sequence, 1);
	Send(lstream->Frame());
	MSG("Sending update signal...");
}

void DataProvider::UpdateFinished(bool delbuff)
{
	if (delbuff)
	{
		delete[] file;
	}

	Do(Command::IDLE);
}

void DataProvider::Upload()
{
	//file_transfer_progress_step = file_size / MAX_DATA_SIZE;
	//if (file_size % MAX_DATA_SIZE > 0)
	//	file_transfer_progress_step++;

	//file_transfer_progress_started = false;
	file_transfer_checking_step = UPLOAD_FILE_EXIST;

	LOG(LOG_DEBUG, "uploading file(%s) size(%i)", file_type == FrameType::FILE_FIRMWARE ? "firmware" : "bootloader", file_size);
	Log("Uploading file. Please wait!");
	Do(Command::UPLOAD);
}

void DataProvider::UploadProgress()
{
	// this is last step
	if (file_transfer_checking_step == UPLOAD_FILE_EXIST || file_transfer_checking_step == UPLOAD_FILE_CHECKING)
	{
		lstream->InitFrame();
		lstream->FrameHeader(file_type == FrameType::FILE_FIRMWARE ? FrameType::CHECK_UPDATE_FIRMWARE : FrameType::CHECK_UPDATE_BOOTLOADER);
		lstream->PushDataToFrame(&sequence, 1);
		lstream->PushDataToFrame((uint8_t*) & file_crc, 2);
		Send(lstream->Frame());
		return;
	}

	// check retry
	if (retry_counter == 5)
	{
		LOG(LOG_DEBUG, "we trying %i times, something wrong!", retry_counter);
		FileTransferFinished();
		return;
	}

	// uploading finished
	if (file_index >= file_size)
	{
		//msgv_addlog(true, msg);

		LOG(LOG_DEBUG, "%i bytes uploaded", file_size);
		file_transfer_checking_step = UPLOAD_FILE_CHECKING;
	}
	else
	{
		LOG(LOG_DEBUG, "%i bytes uploaded", file_index);
		PassProgressToUI(1000*file_index/file_size);

		uint8_t flags = 0;
		if (!file_transfer_progress_started)
		{
			//MSG(msg);
			file_transfer_progress_started = true;
			// set first_part flag
			flags |= FILE_FLAG_FIRST_PART;
		}
		else
		{
			//msgv_addlog(true, msg);
		}

		uint8_t size_of_header_footer = 4; // sequence(1)+flags(1)+crc(2)
		file_partion_size = MAX_DATA_SIZE - size_of_header_footer;
		if ((file_size - file_index) <= file_partion_size)
		{
			// set last_part flag
			flags |= FILE_FLAG_LAST_PART;
			file_partion_size = file_size - file_index;
		}

		lstream->InitFrame();
		lstream->FrameHeader(file_type);
		lstream->PushDataToFrame(& sequence, 1);
		lstream->PushDataToFrame(&flags, 1);
		lstream->PushDataToFrame(file + file_index, file_partion_size);
		Send(lstream->Frame());
	}
}

void DataProvider::FileTransferFinished()
{
	// release file buffer
	delete[] file;
	retry_counter = 0;
	command = Command::IDLE;
	file_transfer_checking_step = 0;
}

void DataProvider::PassProgressToUI(uint16_t value)
{
	cJSON* root = cJSON_CreateObject();
	cJSON* progress = cJSON_CreateNumber(value);
	cJSON_AddItemToObject(root, "value", progress);
	char* json = cJSON_PrintBuffered(root, 128, 0);
	cJSON_Delete(root);
	root = nullptr;
	DataCB(DataType::PROGRESS, std::string(json));
	LOG(LOG_DEBUG, "Pass Progress %i to UI", value);
	free(json);
}

void DataProvider::PassAlertToUI(std::string msg)
{
	cJSON* root = cJSON_CreateObject();
	cJSON* message = cJSON_CreateString(msg.c_str());
	cJSON_AddItemToObject(root, "msg", message);
	char* json = cJSON_PrintBuffered(root, 128, 0);
	cJSON_Delete(root);
	root = nullptr;
	DataCB(DataType::ALERT, std::string(json));
	LOG(LOG_DEBUG, "Pass Alert to UI");
	free(json);
}

#pragma region EmWolf

void DataProvider::EWApply(std::vector<ScenarioItem>& ss, EmWolfSetup& setup)
{
	lstream->InitFrame();
	lstream->FrameHeader(FrameType::EW_START);
	lstream->PushDataToFrame(&sequence, 1);

	ser4cpp::wseq_t wseq(lstream->WriteBuffer().End(), lstream->WriteBuffer().Size());

	EWSerialize(wseq, ss, setup);

	lstream->WriteBuffer().Advance(lstream->WriteBuffer().Size() - wseq.length());
	Send(lstream->Frame());
}

void DataProvider::EWConnect()
{
	MSG("Connecting to EmWolf...");
	try {
		tcp::resolver resolver(asioImpl->context);
		auto query = tcp::resolver::query(tcp::v4(), EMWOLF_IP, std::to_string(EMWOLF_PORT));
		asio::connect(asioImpl->socket, resolver.resolve(query));

		if (asioImpl->socket.is_open())
		{
			is_connected = true;
			MSG("EmWolf Connected!");
			ReadAsync();
		}
		else
			MSG("EmWolf Connect Timeout!");
	}
	catch (std::exception& e) {
		MSG("Connecting failed!");
		std::cerr << "Exception: " << e.what() << std::endl;
	}
}

void DataProvider::EWSave(std::string path, std::vector<ScenarioItem>& ss, EmWolfSetup& setup)
{
	const size_t size = 2048;
	uint8_t buffer[size];

	ser4cpp::wseq_t wseq(buffer, size);

	EWSerialize(wseq, ss, setup);

	SaveFile(path, wseq, wseq.length());
}

void DataProvider::EWLoad(std::string path, std::vector<ScenarioItem>& ss, EmWolfSetup& setup)
{
	const size_t size = 2048;
	uint8_t buffer[size];

}

void DataProvider::EWSerialize(ser4cpp::wseq_t& wseq, std::vector<ScenarioItem>& ss, EmWolfSetup& setup)
{
	setup.Serialize(wseq);

	for (size_t i = 0; i < ss.size(); ++i)
		ss[i].Serialize(wseq);
}

void DataProvider::EWDeserialize(ser4cpp::rseq_t& rseq, std::vector<ScenarioItem>& ss, EmWolfSetup& setup)
{
	setup.Deserialize(rseq);

	for (size_t i = 0; i < ss.size(); ++i)
		ss[i].Deserialize(rseq);
}

#pragma endregion

void DataProvider::SaveFile(std::string path, uint8_t* data, size_t size)
{
	std::ofstream stream(path, std::ios::binary);

	if (!stream)
	{
		Log("Can't open file");
	}
	else
	{
		uint16_t crc = crcFast(data, size);
		stream.write((const char*)data, size);
		stream.write((const char*)&crc, 2);
		stream.close();
		Log("File saved!");
	}
}

void DataProvider::ReadFile(std::string path, uint8_t* data)
{
	std::ifstream stream;
	if (std::filesystem::exists(path))
	{
		auto size = std::filesystem::file_size(path);
		stream.open(path, std::ios::binary);
		stream.read((char*)data, size);
		stream.close();
		Log("Config file loaded");
		PassConfigToUI();
	}
	else
		Log("Can't find the file");
}


#if 0

//const char* DataProvider::FileTypeToString(FileType type)
//{
//	switch (type)
//	{
//	case FileType::FIRMWARE: return "FIRMWARE";
//	case FileType::BOOTLOADER: return "BOOTLOADER";
//	case FileType::EVENTS: return "EVENTS";
//	default: return "Unknown";
//	}
//}

void DataProvider::GetEvents()
{
	Download(FileType::EVENTS);
}


void DataProvider::Download(FileType type)
{
	memset(file_header, 0, sizeof(file_header));
	file_type = (uint8_t)type;

	file_transfer_progress_started = false;
	file_transfer_checking_step = 0;
	sequence = 0;
	file_index = 0;

	MSG_F("Checking %s file status", FileTypeToString(type));
	Do(Command::DOWNLOAD);
}

void DataProvider::DownloadProgress()
{
	if (waiting_for_response)
	{
		if (response_timer.Interval(utils::TimeUnit::MILLI) > RESPONSE_WAIT_INTERVAL)
		{

		}
		return;
	}

	// step 1: get file info
	switch (file_transfer_checking_step)
	{
	case 0:
	{
		uint8_t c[2] = { (uint8_t)CheckType::DOWNLOAD, file_type };
		Request(c, 2);
		file_transfer_checking_step++;
		break;
	}
	case 1:
	{
		if (respose_status == Status::FILE_SIZE)
		{
			file_transfer_progress_step = file_size / MAX_DATA_SIZE;
			if (file_size % MAX_DATA_SIZE > 0)
				file_transfer_progress_step++;

			file = new uint8_t[file_size];
			file_transfer_checking_step++;

			MSG_F("File size: %i", file_size);
		}
		else
			FileTransferFinished();
		break;
	}
	case 2:
	{
		/* [file_sequence(2)]
		*/

		// finished
		if (file_index == file_size)
		{
			MSG("File downloaded successfully");
			size_t s = file_size > sizeof(Events) ? sizeof(Events) : file_size;
			memcpy(&events, file, s);

			//r_cb();

			FileTransferFinished();
			break;
		}

		// check retry
		if (retry_counter == 5)
		{
			LOG(LOG_DEBUG, "we trying %i times, something wrong!", retry_counter);
			FileTransferFinished();
			break;
		}
		lstream->InitFrame();
		lstream->FrameHeader(FrameType::DOWNLOAD, 2);
		lstream->PushDataToFrame((uint8_t*)&sequence, 2);
		Send(lstream->Frame(), true);
		break;
	}
	}
}

void DataProvider::Upload(UpdateType type, uint8_t* data, size_t size)
{
	memset(file_header, 0, sizeof(file_header));
	file_header[0] = (uint8_t)type;
	file = data;
	file_size = size;

	LOG(LOG_DEBUG, "uploading file(%s) size(%i)", type == UpdateType::FIRMWARE ? "firmware" : "bootloader", size);

	Do(Command::UPLOAD);
}


#endif
