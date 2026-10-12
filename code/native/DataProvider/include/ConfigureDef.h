#pragma once

#include <cstdint>

#include "SettingsDef.h"
#include "SCADATypes.h"

enum class StaticBinaryVariation : uint8_t
{
	Group1Var1 = 0,
	Group1Var2 = 1
};

enum class EventBinaryVariation : uint8_t
{
	Group2Var1 = 0,
	Group2Var2 = 1,
	Group2Var3 = 2
};

enum class StaticAnalogVariation : uint8_t
{
	Group30Var1 = 0,
	Group30Var2 = 1,
	Group30Var3 = 2,
	Group30Var4 = 3,
	Group30Var5 = 4,
	Group30Var6 = 5
};

enum class EventAnalogVariation : uint8_t
{
	Group32Var1 = 0,
	Group32Var2 = 1,
	Group32Var3 = 2,
	Group32Var4 = 3,
	Group32Var5 = 4,
	Group32Var6 = 5,
	Group32Var7 = 6,
	Group32Var8 = 7
};

enum class StaticDoubleBinaryVariation : uint8_t
{
	Group3Var2 = 0
};

enum class EventDoubleBinaryVariation : uint8_t
{
	Group4Var1 = 0,
	Group4Var2 = 1,
	Group4Var3 = 2
};

enum class StaticBinaryOutputStatusVariation : uint8_t
{
	Group10Var2 = 0
};

enum class EventBinaryOutputStatusVariation : uint8_t
{
	Group11Var1 = 0,
	Group11Var2 = 1
};

enum class StaticAnalogOutputStatusVariation : uint8_t
{
	Group40Var1 = 0,
	Group40Var2 = 1,
	Group40Var3 = 2,
	Group40Var4 = 3
};

enum class EventAnalogOutputStatusVariation : uint8_t
{
	Group42Var1 = 0,
	Group42Var2 = 1,
	Group42Var3 = 2,
	Group42Var4 = 3,
	Group42Var5 = 4,
	Group42Var6 = 5,
	Group42Var7 = 6,
	Group42Var8 = 7
};

enum class StaticCounterVariation : uint8_t
{
	Group20Var1 = 0,
	Group20Var2 = 1,
	Group20Var5 = 2,
	Group20Var6 = 3
};

enum class EventCounterVariation : uint8_t
{
	Group22Var1 = 0,
	Group22Var2 = 1,
	Group22Var5 = 2,
	Group22Var6 = 3
};

enum class StaticOctetStringVariation : uint8_t
{
	Group110Var0 = 0
};
