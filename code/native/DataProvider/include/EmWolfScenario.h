#ifndef SCENARIO_H
#define SCENARIO_H

#include <stdint.h>
#include <vector>
#include <string>

#include "EmWolfUtils.h"

#include <ser4cpp/container/WSeq.h>
#include <ser4cpp/container/SequenceTypes.h>
#include <ser4cpp/serialization/LittleEndian.h>

enum class EndType :uint8_t {
    DI_TOGGLE, CYCLES, TIME, INFINIT
};
enum class EWDI :uint8_t {
    DI_1, DI_2, DI_3, DI_4
};
enum class Harmonic :uint8_t {
    _2, _3, _4, _5, _6, _7, _8, _9, _10, _11, _12, _13, _14, _15
};

class ScenarioEndStrategy
{
public:
    ScenarioEndStrategy()
        : type(EndType::INFINIT), di(EWDI::DI_1), value(1), delay(0) {};
    void Serialize(ser4cpp::wseq_t& wseq) const 
    {
        ser4cpp::UInt8::write_to(wseq, (uint8_t)type);
        ser4cpp::UInt8::write_to(wseq, (uint8_t)di);

        ser4cpp::UInt32::write_to(wseq, value);
        ser4cpp::UInt32::write_to(wseq, delay);
    }
    void Deserialize(ser4cpp::rseq_t& rseq) 
    {
        uint8_t temp;
        ser4cpp::UInt8::read_from(rseq, temp);
        type = (EndType)temp;
        ser4cpp::UInt8::read_from(rseq, temp);
        di = (EWDI)temp;

        ser4cpp::UInt32::read_from(rseq, value);
        ser4cpp::UInt32::read_from(rseq, delay);
    }

    EndType type;
    EWDI di;
    // if type == CYCLES	-> value is number of cycles
    // if type == TIME		-> value is time in second
    uint32_t value, delay;
};

class AnalogItem
{
public:
    AnalogItem():amplitude(0),frequency(50),hrm1(0),hrm2(0),phase(0),
        hrm1_num(Harmonic::_2), hrm2_num(Harmonic::_2), enabled(false) {}
    void Serialize(ser4cpp::wseq_t& wseq) const 
    {
        ser4cpp::SingleFloat::write_to(wseq, amplitude);
        ser4cpp::SingleFloat::write_to(wseq, frequency);
        ser4cpp::SingleFloat::write_to(wseq, hrm1);
        ser4cpp::SingleFloat::write_to(wseq, hrm2);

        ser4cpp::UInt16::write_to(wseq, phase);

        ser4cpp::UInt8::write_to(wseq, (uint8_t)hrm1_num);
        ser4cpp::UInt8::write_to(wseq, (uint8_t)hrm2_num);
    }
    void Deserialize(ser4cpp::rseq_t& rseq) 
    {
        ser4cpp::SingleFloat::read_from(rseq, amplitude);
        ser4cpp::SingleFloat::read_from(rseq, frequency);
        ser4cpp::SingleFloat::read_from(rseq, hrm1);
        ser4cpp::SingleFloat::read_from(rseq, hrm2);

        ser4cpp::UInt16::read_from(rseq, phase);

        uint8_t temp;
        ser4cpp::UInt8::read_from(rseq, temp);
        hrm1_num = (Harmonic)temp;
        ser4cpp::UInt8::read_from(rseq, temp);
        hrm2_num = (Harmonic)temp;
    }
    float amplitude;
    float frequency;
    float hrm1, hrm2;
    uint16_t phase;
    Harmonic hrm1_num, hrm2_num;
    bool enabled;
};

class DigitalItem
{
public:
    DigitalItem(): enabled(false), value(false){}
    bool enabled, value;
};

class ScenarioItem
{
public:
    ScenarioItem(std::string name)
        :
        name(name), isOpen(false), analogs(8), digitals(8), ends()
    {
    }

    void Serialize(ser4cpp::wseq_t& wseq) const
    {
        for (size_t i = 0; i < analogs.size(); ++i)
            analogs[i].Serialize(wseq);

        ends.Serialize(wseq);
    }

    void Deserialize(ser4cpp::rseq_t& rseq) 
    {
        for (size_t i = 0; i < analogs.size(); ++i)
            analogs[i].Deserialize(rseq);

        ends.Deserialize(rseq);
    }

    std::string name;
    bool isOpen;
    std::vector<AnalogItem> analogs;
    std::vector<DigitalItem> digitals;

    ScenarioEndStrategy ends;
};

class Scenario
{
public:
    Scenario();
    void Deserialize(ser4cpp::rseq_t& rseq) 
    {
        va.Deserialize(rseq);
        vb.Deserialize(rseq);
        vc.Deserialize(rseq);
        vt.Deserialize(rseq);
        ia.Deserialize(rseq);
        ib.Deserialize(rseq);
        ic.Deserialize(rseq);
        in.Deserialize(rseq);

        ends.Deserialize(rseq);
    }
    AnalogItem va, vb, vc, vt, ia, ib, ic, in;
	ScenarioEndStrategy ends;
};

#endif // SCENARIO_H
