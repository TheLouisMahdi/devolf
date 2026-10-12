#ifndef DATA_PROVIDER_H
#define DATA_PROVIDER_H

#include <iostream>
#include <functional>
#include <memory>
#include <thread>

#include "Settings.h"
#include "LightStream.h"
#include "DataProviderTypes.h"
#include "Timer.h"
#include "MeasureType.h"
#include "cJSON_Imp.h"
#include "crc.h"
#include "Event.h"

#include "EmWolfScenario.h"
#include "EmWolfSetup.h"

#define USER_NAME   (user == 0 ? "WolfEye" : "EmWolf")

#define DEFAULT_IP      "192.168.137.10"
#define TCP_PORT        6536

#define EMWOLF_IP       "192.168.137.1"// "127.0.0.1"// 
#define EMWOLF_PORT     666

#define host            dev.ip

#define RES_TIMER_NOT_WAIT      0
#define RES_TIMER_WAIT          1
#define RES_TIMER_TIMEOUT       2

#define STATUS_UPDATE_INTERVAL          100

enum class DataType :uint8_t
{
    INFO, MEASUREMENTS, CONFIG, EVENTS, PROGRESS, ALERT
};

using data_cb_t = std::function<void(DataType, std::string)>;
using log_cb_t = std::function<void(std::string)>;
using request_cb_t = std::function<void()>;

enum class REQ_DATA :uint8_t
{
    MEASUREMENTS, SETTINGS
};

enum class Command :uint8_t
{
    IDLE = 0,
    GET_MEASUREMENT,
    GET_SETTINGS,
    GET_INFO,
    GET_EVENTS,
    SAVE_SETTING,
    RESET,
    GET_SIGNAL,
    UPLOAD,

    DOWNLOAD,
    UPDATE,
};

enum class CommandStatus : uint8_t
{
    SUCCESS, TIMEOUT
};

enum class AfterUpload :uint8_t
{
    IDLE, UPDATE
};

class DataProvider :public IFrame
{
public:
    DataProvider(data_cb_t, log_cb_t);
    ~DataProvider();
    void Start(const char* ip, uint16_t port);
    void Stop();
    void Info();

    //void Upload(UpdateType, uint8_t*, size_t);
    void Upload();
    void Update(UpdateType, std::string path);
    void GetEvents();

    void LoadSetting(std::string);
    void LoadSetting();
    void SaveSettings(std::string, std::string);
    void SaveSettingsToFile(std::string);
    void SaveSettings(std::string);

    void DeviceTypeChanged(DeviceType);
    void LoadDefault();

    void Do(Command);
    void Do(Command, request_cb_t&);
    bool IsCommandIDLE();
    void CommandExecuted(bool success = true);

    bool ICMPPing(std::string ip, uint32_t timeout, bool do_log);

    std::shared_ptr<Settings> settings;
    Configure* Config() { return &settings->config; }
    Configure* DefConfig() { return &settings->temp; }

    std::shared_ptr<BIs> bi;
    std::shared_ptr<AIs> ai;
    std::vector<const BI*> bi_list;
    std::vector<const AI*> ai_list;

    Events events;
    void EventToString(uint16_t, char*, size_t);

    device_info_t dev;
    status_t status;

    Signal signal;

    bool is_connected, is_thread_running, is_settings_read, is_tcp_connected, is_timeout;
    uint8_t save_status;

    data_cb_t DataCB;
    log_cb_t LogCB;
    request_cb_t ReqCB;

#pragma region EmWolf
        void EWApply(std::vector<ScenarioItem>&, EmWolfSetup&);
        void EWSave(std::string, std::vector<ScenarioItem>&, EmWolfSetup&);
        void EWLoad(std::string, std::vector<ScenarioItem>&, EmWolfSetup&);
    private:
        void EWConnect();
        void EWSerialize(ser4cpp::wseq_t&, std::vector<ScenarioItem>&, EmWolfSetup&);
        void EWDeserialize(ser4cpp::rseq_t&, std::vector<ScenarioItem>&, EmWolfSetup&);
#pragma endregion

private:
    std::thread t;
    bool kill_thread;

    struct ASIOImpl;
    std::unique_ptr<ASIOImpl> asioImpl;

    Command command;
    std::shared_ptr<LightStream>lstream;
    //std::shared_ptr<MessageViewer> msgv;

    void UpdateStatus();

    void OnFrame(SFrame&) override;

    void ReadAsync();

    void Connect();
    void Send(LSBuff*);
    void Request(FrameType);

    void UpdateConfig();
    void ReadConfig();
    void UploadProgress();
    void FileTransferFinished();
    void DownloadProgress();

    void GetSignal();
    void ResetDevice();

    void UpdateProgress();
    void UpdateFinished(bool);

    //void Download(FileType);
    //const char* FileTypeToString(FileType);

    void Wait();
    uint8_t Timeout(int);
    bool WaitToResponse();

    // file upload/download
    //uint8_t file_header[3];
    FrameType file_type;
    uint8_t* file;
    size_t file_size;// size of the uploading file
    size_t file_index;// index of buffer that uploaded
    size_t file_partion_size;// the size of trying to upload
    uint16_t file_transfer_progress_step, file_crc;
    bool file_transfer_progress_started;
    uint8_t file_transfer_checking_step;
    AfterUpload after_upload;

    uint8_t retry_counter;
    bool waiting_for_response;
    Status respose_status;
    uint8_t sequence = 1;


    utils::Timer response_timer;

    void Log(const char*);

    void PassAlertToUI(std::string);
    void PassProgressToUI(uint16_t);
    void PassInfoToUI(cJSON* obj = nullptr);
    void PassConfigToUI();
    void PassEventsToUI();
    bool PassMeasurementToUI();

    inline cJSON* MeasurementItem(const char* m_name, uint16_t m_value, uint16_t id, uint16_t dnp)
    {
        cJSON* item = cJSON_CreateObject();
        cJSON* name = cJSON_CreateString(m_name);
        cJSON* val = cJSON_CreateNumber(m_value);
        cJSON_AddItemToObject(item, "name", name);
        cJSON_AddItemToObject(item, "val", val);
        cJSON_AddItemToObject(item, "id", cJSON_CreateNumber(id));
        cJSON_AddItemToObject(item, "dnp_index", cJSON_CreateNumber(dnp));

        return item;
    }

    void InfoDeserialize(uint8_t*, size_t);
    void MeasurementDeserialize(uint8_t*, size_t);
    void SettingsDeserialize(uint8_t*, size_t);
    void EventsDeserialize(uint8_t*, size_t);

    void ReloadPoints();

    bool is_set_callback = false;
    uint8_t user = 0;

    void SaveFile(std::string, uint8_t*, size_t);
    void ReadFile(std::string, uint8_t*);
};


#endif // !DATA_PROVIDER_H