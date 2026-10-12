#ifndef EMWOLFUTILS_H
#define EMWOLFUTILS_H

#define SERIALIZE(buffer,v) do{\
    const uint8_t* p = reinterpret_cast<const uint8_t*>(&v); \
    buffer.insert(buffer.end(), p, p + sizeof(v)); \
}while (0);
#define DESERIALIZE(data,v) do{\
    memcpy(&v, data + offset, sizeof(v)); \
    offset += sizeof(v); \
}while (0);

#endif // EMWOLFUTILS_H
