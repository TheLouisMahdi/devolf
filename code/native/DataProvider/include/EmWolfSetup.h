#ifndef EMWOLFSETUP_H
#define EMWOLFSETUP_H

#include <stdint.h>
#include <string.h>
#include <vector>

#include "EmWolfUtils.h"

#include <ser4cpp/container/WSeq.h>
#include <ser4cpp/container/SequenceTypes.h>
#include <ser4cpp/serialization/LittleEndian.h>

class EmWolfSetup
{
public:
    void Serialize(ser4cpp::wseq_t& wseq) const
    {
        ser4cpp::UInt16::write_to(wseq, offsets.va);
        ser4cpp::UInt16::write_to(wseq, offsets.vb);
        ser4cpp::UInt16::write_to(wseq, offsets.vc);
        ser4cpp::UInt16::write_to(wseq, offsets.vt);
        ser4cpp::UInt16::write_to(wseq, offsets.ia);
        ser4cpp::UInt16::write_to(wseq, offsets.ib);
        ser4cpp::UInt16::write_to(wseq, offsets.ic);
        ser4cpp::UInt16::write_to(wseq, offsets.in);

        ser4cpp::SingleFloat::write_to(wseq, sample_time);
    }
    void Deserialize(ser4cpp::rseq_t& rseq) 
    {
        ser4cpp::UInt16::read_from(rseq, offsets.va);
        ser4cpp::UInt16::read_from(rseq, offsets.vb);
        ser4cpp::UInt16::read_from(rseq, offsets.vc);
        ser4cpp::UInt16::read_from(rseq, offsets.vt);
        ser4cpp::UInt16::read_from(rseq, offsets.ia);
        ser4cpp::UInt16::read_from(rseq, offsets.ib);
        ser4cpp::UInt16::read_from(rseq, offsets.ic);
        ser4cpp::UInt16::read_from(rseq, offsets.in);

        ser4cpp::SingleFloat::read_from(rseq, sample_time);
    }
    struct {
        uint16_t va = 2048, vb = 2048, vc = 2048, vt = 2048, ia = 2048, ib = 2048, ic = 2048, in = 2048;
    }offsets;
    float sample_time = 8.2;
};

#endif // EMWOLFSETUP_H
