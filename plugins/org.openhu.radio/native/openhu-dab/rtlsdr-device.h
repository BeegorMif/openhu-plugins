// RTL-SDR input for the dab-cmdline library (deviceHandler): 2.048 MS/s, linked against librtlsdr (the
// dab-cmdline handler loads it with dlopen and prints to stdout, which carries openhu-dab's PCM).
//
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <atomic>
#include <complex>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "device-handler.h"
#include "ringbuffer.h"

struct rtlsdr_dev;

class DeviceError: public std::runtime_error
{
public:
    // code: "no-device", "device-busy", "device"
    DeviceError(const std::string& code, const std::string& message)
        : std::runtime_error(message)
        , code(code)
    {
    }
    std::string code;
};

class RtlSdrDevice: public deviceHandler
{
public:
    // gainTenthDb < 0: automatic gain (tuner AGC)
    RtlSdrDevice(int index, int ppm, int gainTenthDb, bool biasTee);
    ~RtlSdrDevice() override;

    bool restartReader(int32_t frequency) override;
    void stopReader() override;
    int32_t getSamples(std::complex<float>* buffer, int32_t size) override;
    int32_t Samples() override;
    void resetBuffer() override;
    int16_t bitDepth() override { return 8; }

    std::string name() const { return name_; }
    int gain() const { return gain_; }  // tenths of dB, -1 automatic
    // the stick was unplugged (the USB transfer ended without stopReader)
    bool lost() const { return lost_.load(); }

    static constexpr int32_t cSampleRate = 2048000;

private:
    void readLoop();
    static void callback(unsigned char* buffer, uint32_t length, void* context);

    rtlsdr_dev* device_ = nullptr;
    std::string name_;
    int gain_ = -1;
    RingBuffer<uint8_t> buffer_;
    std::thread reader_;
    std::atomic<bool> running_{false};
    std::atomic<bool> stopping_{false};
    std::atomic<bool> lost_{false};
};
