// SPDX-License-Identifier: GPL-3.0-or-later

#include "rtlsdr-device.h"

#include <rtl-sdr.h>

#include <cmath>
#include <cstdlib>

namespace
{

// about 1 s of samples (2 bytes per I/Q sample); a power of two for the ring buffer
constexpr uint32_t cBufferBytes = 4 * 1024 * 1024;
constexpr uint32_t cTransferBytes = 16 * 16384;

float convert(uint8_t value)
{
    return (static_cast<float>(value) - 127.5f) / 128.0f;
}

}

RtlSdrDevice::RtlSdrDevice(int index, int ppm, int gainTenthDb, bool biasTee)
    : buffer_(cBufferBytes)
{
    if(rtlsdr_get_device_count() == 0)
    {
        // same text as rtl_fm, the radio plugin knows it
        throw DeviceError("no-device", "No supported devices found.");
    }
    const char* deviceName = rtlsdr_get_device_name(index);
    name_ = deviceName != nullptr ? deviceName : "RTL-SDR";
    if(rtlsdr_open(&device_, index) < 0 || device_ == nullptr)
    {
        device_ = nullptr;
        throw DeviceError("device-busy", "Failed to open rtlsdr device #" + std::to_string(index) + ".");
    }
    if(rtlsdr_set_sample_rate(device_, cSampleRate) < 0)
    {
        rtlsdr_close(device_);
        device_ = nullptr;
        throw DeviceError("device", "Cannot set the sample rate of the RTL-SDR stick");
    }
    if(ppm != 0)
    {
        rtlsdr_set_freq_correction(device_, ppm);
    }
    if(gainTenthDb < 0)
    {
        rtlsdr_set_tuner_gain_mode(device_, 0);
    }
    else
    {
        // nearest gain the tuner supports
        rtlsdr_set_tuner_gain_mode(device_, 1);
        const int count = rtlsdr_get_tuner_gains(device_, nullptr);
        if(count > 0)
        {
            std::vector<int> gains(count);
            rtlsdr_get_tuner_gains(device_, gains.data());
            int best = gains[0];
            for(int value: gains)
            {
                if(std::abs(value - gainTenthDb) < std::abs(best - gainTenthDb))
                {
                    best = value;
                }
            }
            rtlsdr_set_tuner_gain(device_, best);
            gain_ = best;
        }
    }
    // antenna power (active antennas), RTL-SDR Blog V3/V4 and compatible sticks
    rtlsdr_set_bias_tee(device_, biasTee ? 1 : 0);
}

RtlSdrDevice::~RtlSdrDevice()
{
    stopReader();
    if(device_ != nullptr)
    {
        rtlsdr_set_bias_tee(device_, 0);
        rtlsdr_close(device_);
    }
}

void RtlSdrDevice::callback(unsigned char* data, uint32_t length, void* context)
{
    auto* self = static_cast<RtlSdrDevice*>(context);
    // a full buffer (the decoder is too slow) drops the newest samples, the decoder resyncs
    self->buffer_.putDataIntoBuffer(data, static_cast<int32_t>(length));
}

void RtlSdrDevice::readLoop()
{
    rtlsdr_read_async(device_, &RtlSdrDevice::callback, this, 0, cTransferBytes);
    if(!stopping_.load())
    {
        lost_.store(true);
    }
}

bool RtlSdrDevice::restartReader(int32_t frequency)
{
    stopReader();
    lastFrequency = frequency;
    buffer_.FlushRingBuffer();
    if(rtlsdr_set_center_freq(device_, static_cast<uint32_t>(frequency)) < 0)
    {
        return false;
    }
    rtlsdr_reset_buffer(device_);
    stopping_.store(false);
    running_.store(true);
    reader_ = std::thread(&RtlSdrDevice::readLoop, this);
    return true;
}

void RtlSdrDevice::stopReader()
{
    if(!running_.exchange(false))
    {
        return;
    }
    stopping_.store(true);
    rtlsdr_cancel_async(device_);
    if(reader_.joinable())
    {
        reader_.join();
    }
}

int32_t RtlSdrDevice::getSamples(std::complex<float>* output, int32_t size)
{
    std::vector<uint8_t> raw(2 * static_cast<size_t>(size));
    const int32_t bytes = buffer_.getDataFromBuffer(raw.data(), 2 * size);
    for(int32_t i = 0; i < bytes / 2; ++i)
    {
        output[i] = std::complex<float>(convert(raw[2 * i]), convert(raw[2 * i + 1]));
    }
    return bytes / 2;
}

int32_t RtlSdrDevice::Samples()
{
    return buffer_.GetRingBufferReadAvailable() / 2;
}

void RtlSdrDevice::resetBuffer()
{
    buffer_.FlushRingBuffer();
}
