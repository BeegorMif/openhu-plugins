// openhu-dab: DAB/DAB+ receiver for the OpenHU radio plugin with an RTL-SDR stick, built on the DAB library of
// dab-cmdline. No network listener: audio as raw PCM on stdout, everything else as JSON lines on the event fd.
//
//   openhu-dab --channel 7A [--service 0xD882]      tune a Band III channel, report ensemble and services,
//                                                   play the service (PCM on stdout) until SIGTERM
//   openhu-dab --scan [--channels 5C,7A]            all channels (or the given ones) one after the other, exits
//
// Events (one JSON object per line, "event" says which): device, tuned, sync, ensemble, service, playing, audio,
// dls, slide, signal, scan, channel, done, error. See --help and the radio plugin's README.
//
// SPDX-License-Identifier: GPL-3.0-or-later

#include <fcntl.h>
#include <getopt.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <samplerate.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "dab-api.h"
#include "dab-processor.h"
#include "rtlsdr-device.h"

namespace
{

using Clock = std::chrono::steady_clock;

// Band III (ETSI EN 300 401), kHz
const std::vector<std::pair<std::string, int>> cChannels = {
    {"5A", 174928}, {"5B", 176640}, {"5C", 178352}, {"5D", 180064},
    {"6A", 181936}, {"6B", 183648}, {"6C", 185360}, {"6D", 187072},
    {"7A", 188928}, {"7B", 190640}, {"7C", 192352}, {"7D", 194064},
    {"8A", 195936}, {"8B", 197648}, {"8C", 199360}, {"8D", 201072},
    {"9A", 202928}, {"9B", 204640}, {"9C", 206352}, {"9D", 208064},
    {"10A", 209936}, {"10B", 211648}, {"10C", 213360}, {"10D", 215072},
    {"11A", 216928}, {"11B", 218640}, {"11C", 220352}, {"11D", 222064},
    {"12A", 223936}, {"12B", 225648}, {"12C", 227360}, {"12D", 229072},
    {"13A", 230784}, {"13B", 232496}, {"13C", 234208}, {"13D", 235776}, {"13E", 237488}, {"13F", 239200},
};

std::atomic<bool> gStop{false};

void onSignal(int)
{
    gStop.store(true);
}

// --- JSON -------------------------------------------------------------------------------

std::string quote(const std::string& text)
{
    std::string result = "\"";
    for(unsigned char c: text)
    {
        switch(c)
        {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if(c < 0x20)
            {
                char escaped[8];
                std::snprintf(escaped, sizeof(escaped), "\\u%04x", c);
                result += escaped;
            }
            else
            {
                result += static_cast<char>(c);
            }
        }
    }
    return result + "\"";
}

class Json
{
public:
    explicit Json(const std::string& event) { add("event", event); }
    Json& add(const std::string& key, const std::string& value) { return raw(key, quote(value)); }
    Json& add(const std::string& key, const char* value) { return raw(key, quote(value)); }
    Json& add(const std::string& key, bool value) { return raw(key, value ? "true" : "false"); }
    Json& add(const std::string& key, int value) { return raw(key, std::to_string(value)); }
    Json& raw(const std::string& key, const std::string& value)
    {
        text_ += (text_.empty() ? "{" : ",") + quote(key) + ":" + value;
        return *this;
    }
    std::string line() const { return text_ + "}\n"; }

private:
    std::string text_;
};

std::string hex(uint32_t value, int digits)
{
    char text[16];
    std::snprintf(text, sizeof(text), "0x%0*X", digits, value);
    return text;
}

std::string sidKey(uint32_t sid)
{
    // 16 bit programme services, 32 bit data services (like the radio plugin's keys)
    return sid <= 0xFFFF ? hex(sid, 4) : hex(sid, 8);
}

std::string trim(const std::string& text)
{
    const auto begin = text.find_first_not_of(" \t\r\n");
    if(begin == std::string::npos)
    {
        return "";
    }
    return text.substr(begin, text.find_last_not_of(" \t\r\n") - begin + 1);
}

std::string base64(const uint8_t* data, size_t size)
{
    static const char* table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string result;
    result.reserve((size + 2) / 3 * 4);
    for(size_t i = 0; i < size; i += 3)
    {
        uint32_t chunk = data[i] << 16;
        if(i + 1 < size) chunk |= data[i + 1] << 8;
        if(i + 2 < size) chunk |= data[i + 2];
        result += table[(chunk >> 18) & 63];
        result += table[(chunk >> 12) & 63];
        result += i + 1 < size ? table[(chunk >> 6) & 63] : '=';
        result += i + 2 < size ? table[chunk & 63] : '=';
    }
    return result;
}

bool writeAll(int fd, const char* data, size_t size)
{
    while(size > 0)
    {
        const ssize_t written = ::write(fd, data, size);
        if(written < 0)
        {
            if(errno == EINTR)
            {
                continue;
            }
            return false;
        }
        data += written;
        size -= static_cast<size_t>(written);
    }
    return true;
}

// --- events -------------------------------------------------------------------------------

class Events
{
public:
    void setFd(int fd) { fd_ = fd; }
    void send(const Json& json)
    {
        const std::string line = json.line();
        std::lock_guard<std::mutex> lock(mutex_);
        writeAll(fd_, line.data(), line.size());
    }

private:
    int fd_ = 2;
    std::mutex mutex_;
};

Events gEvents;

void fail(const std::string& code, const std::string& message)
{
    gEvents.send(Json("error").add("code", code).add("message", message));
}

// --- audio output ---------------------------------------------------------------------------
// The decoder delivers 16 bit stereo at the service's rate (48/32/24/16 kHz). The output has one fixed rate
// (libsamplerate), so the reader (pacat) never has to restart. A writer thread decouples the decoder from the pipe;
// more than 2 s queued (the reader stalls) drops the oldest audio.

class AudioOutput
{
public:
    AudioOutput(int fd, int rate)
        : fd_(fd)
        , rate_(rate)
    {
        writer_ = std::thread(&AudioOutput::writeLoop, this);
    }

    ~AudioOutput()
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            done_ = true;
        }
        wake_.notify_all();
        writer_.join();
        if(converter_ != nullptr)
        {
            src_delete(converter_);
        }
    }

    void push(const int16_t* samples, int count, int rate)
    {
        if(count <= 0 || rate <= 0)
        {
            return;
        }
        const int outputRate = rate_ > 0 ? rate_ : rate;
        if(!announced_ || outputRate != announcedRate_)
        {
            announced_ = true;
            announcedRate_ = outputRate;
            gEvents.send(Json("audio").add("rate", outputRate).add("channels", 2).add("format", "s16le")
                             .add("sourceRate", rate));
        }
        std::vector<int16_t> output;
        if(outputRate == rate)
        {
            output.assign(samples, samples + count);
        }
        else
        {
            output = convert(samples, count, rate, outputRate);
        }
        if(output.empty())
        {
            return;
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            queue_.push_back(std::move(output));
            queued_ += queue_.back().size();
            const size_t limit = static_cast<size_t>(outputRate) * 2 * 2;
            while(queued_ > limit && queue_.size() > 1)
            {
                queued_ -= queue_.front().size();
                queue_.pop_front();
            }
        }
        wake_.notify_one();
    }

private:
    std::vector<int16_t> convert(const int16_t* samples, int count, int rate, int outputRate)
    {
        int error = 0;
        if(converter_ == nullptr)
        {
            converter_ = src_new(SRC_SINC_FASTEST, 2, &error);
            if(converter_ == nullptr)
            {
                return {};
            }
        }
        if(rate != converterRate_)
        {
            src_reset(converter_);
            converterRate_ = rate;
        }
        const int frames = count / 2;
        input_.resize(static_cast<size_t>(count));
        src_short_to_float_array(samples, input_.data(), count);
        const double ratio = static_cast<double>(outputRate) / rate;
        const int outputFrames = static_cast<int>(frames * ratio) + 64;
        converted_.resize(static_cast<size_t>(outputFrames) * 2);
        SRC_DATA data{};
        data.data_in = input_.data();
        data.input_frames = frames;
        data.data_out = converted_.data();
        data.output_frames = outputFrames;
        data.src_ratio = ratio;
        if(src_process(converter_, &data) != 0)
        {
            return {};
        }
        std::vector<int16_t> output(static_cast<size_t>(data.output_frames_gen) * 2);
        src_float_to_short_array(converted_.data(), output.data(), static_cast<int>(output.size()));
        return output;
    }

    void writeLoop()
    {
        while(true)
        {
            std::vector<int16_t> chunk;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait(lock, [this] { return done_ || !queue_.empty(); });
                // stopping: what is still queued is dropped (the reader may be gone or stalled)
                if(done_)
                {
                    return;
                }
                chunk = std::move(queue_.front());
                queue_.pop_front();
                queued_ -= chunk.size();
            }
            // reader gone (EPIPE): openhu-dab ends
            if(!broken_.load() && !writeAll(fd_, reinterpret_cast<const char*>(chunk.data()),
                                            chunk.size() * sizeof(int16_t)))
            {
                broken_.store(true);
                gStop.store(true);
            }
        }
    }

    int fd_;
    int rate_;
    bool announced_ = false;
    int announcedRate_ = 0;
    SRC_STATE* converter_ = nullptr;
    int converterRate_ = 0;
    std::vector<float> input_;
    std::vector<float> converted_;
    std::mutex mutex_;
    std::condition_variable wake_;
    std::deque<std::vector<int16_t>> queue_;
    size_t queued_ = 0;
    bool done_ = false;
    std::atomic<bool> broken_{false};
    std::thread writer_;
};

// --- receiver state (the library calls back from its threads) -------------------------------------

struct Options
{
    std::string channel;
    uint32_t service = 0;
    bool scan = false;
    std::vector<std::string> channels;
    int device = 0;
    int gain = -1;  // tenths of dB, -1 automatic
    int ppm = 0;
    bool biasTee = false;
    int eventsFd = 2;
    std::string slides;
    int rate = 48000;
    double syncSeconds = 3;
    double scanSeconds = 10;
};

struct State
{
    std::mutex mutex;
    int generation = 0;
    std::string channel;
    bool timeSynced = false;
    bool syncReported = false;
    std::string ensembleLabel;
    uint32_t ensembleId = 0;
    bool ensembleKnown = false;
    std::map<uint32_t, std::string> names;  // SId -> label, from the FIC
    uint32_t playing = 0;  // service whose PAD (DLS, slides) arrives
    int slideCounter = 0;
    std::deque<std::string> slideFiles;
    int snr = 0;
    int fic = -1;
    std::chrono::time_point<Clock> lastSignal;
};

State gState;
Options gOptions;
AudioOutput* gAudio = nullptr;

void syncSignal(bool synced, void*)
{
    std::lock_guard<std::mutex> lock(gState.mutex);
    gState.timeSynced = synced;
    gState.syncReported = true;
}

void systemData(bool synced, int16_t snr, int32_t offset, void*)
{
    (void)offset;
    bool send = false;
    int fic = 0;
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        gState.timeSynced = synced;
        gState.snr = snr;
        fic = gState.fic;
        // at most every 5 s: the plugin may show it, nobody needs it once per second
        if(Clock::now() - gState.lastSignal > std::chrono::seconds(5))
        {
            gState.lastSignal = Clock::now();
            send = true;
        }
    }
    if(send)
    {
        gEvents.send(Json("signal").add("synced", synced).add("snr", static_cast<int>(snr)).add("fic", fic));
    }
}

void ficQuality(int16_t quality, void*)
{
    std::lock_guard<std::mutex> lock(gState.mutex);
    gState.fic = quality;
}

void ensembleName(const std::string& name, int32_t id, void*)
{
    std::lock_guard<std::mutex> lock(gState.mutex);
    gState.ensembleLabel = trim(name);
    gState.ensembleId = static_cast<uint32_t>(id) & 0xFFFF;
    gState.ensembleKnown = true;
}

void serviceName(const std::string& name, int32_t sid, uint16_t subChannel, void*)
{
    (void)subChannel;
    std::lock_guard<std::mutex> lock(gState.mutex);
    gState.names.emplace(static_cast<uint32_t>(sid), trim(name));
}

void audioOut(int16_t* buffer, int size, int rate, bool stereo, void*)
{
    (void)stereo;  // always two channels (mono is duplicated by the library)
    if(gAudio != nullptr)
    {
        gAudio->push(buffer, size, rate);
    }
}

void dynamicLabel(const char* text, void*)
{
    uint32_t sid = 0;
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        sid = gState.playing;
    }
    if(sid != 0)
    {
        gEvents.send(Json("dls").add("sid", sidKey(sid)).add("text", trim(text)));
    }
}

std::string imageType(const uint8_t* data, int size, int subType)
{
    if(size >= 8 && std::memcmp(data, "\x89PNG\r\n\x1a\n", 8) == 0) return "image/png";
    if(size >= 3 && data[0] == 0xFF && data[1] == 0xD8 && data[2] == 0xFF) return "image/jpeg";
    if(size >= 4 && std::memcmp(data, "GIF8", 4) == 0) return "image/gif";
    if(size >= 2 && data[0] == 'B' && data[1] == 'M') return "image/bmp";
    // MOT content subtype (ETSI TS 101 756): 0 GIF, 1 JFIF, 2 BMP, 3 PNG
    switch(subType)
    {
    case 0: return "image/gif";
    case 1: return "image/jpeg";
    case 2: return "image/bmp";
    case 3: return "image/png";
    }
    return "application/octet-stream";
}

std::string extension(const std::string& mime)
{
    const auto slash = mime.find('/');
    const std::string type = slash == std::string::npos ? "bin" : mime.substr(slash + 1);
    return type == "jpeg" ? "jpg" : type == "octet-stream" ? "bin" : type;
}

void motData(uint8_t* data, int size, const char* name, int subType, void*)
{
    uint32_t sid = 0;
    int counter = 0;
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        sid = gState.playing;
        counter = ++gState.slideCounter;
    }
    if(sid == 0 || size <= 0)
    {
        return;
    }
    const std::string mime = imageType(data, size, subType);
    Json json("slide");
    json.add("sid", sidKey(sid)).add("mime", mime).add("name", name != nullptr ? name : "").add("size", size);
    if(gOptions.slides.empty())
    {
        json.add("data", base64(data, static_cast<size_t>(size)));
        gEvents.send(json);
        return;
    }
    // a new file per slide (written completely before the event), the last two are kept
    const std::string path = gOptions.slides + "/slide-" + std::to_string(::getpid()) + "-" + std::to_string(counter)
        + "." + extension(mime);
    const std::string temporary = path + ".tmp";
    FILE* file = std::fopen(temporary.c_str(), "wb");
    if(file == nullptr)
    {
        fail("slides", "cannot write " + temporary + ": " + std::strerror(errno));
        return;
    }
    const bool written = std::fwrite(data, 1, static_cast<size_t>(size), file) == static_cast<size_t>(size);
    if(std::fclose(file) != 0 || !written || std::rename(temporary.c_str(), path.c_str()) != 0)
    {
        std::remove(temporary.c_str());
        fail("slides", "cannot write " + path);
        return;
    }
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        gState.slideFiles.push_back(path);
        while(gState.slideFiles.size() > 2)
        {
            std::remove(gState.slideFiles.front().c_str());
            gState.slideFiles.pop_front();
        }
    }
    gEvents.send(json.add("path", path));
}

// --- receiver -------------------------------------------------------------------------------

int channelFrequency(const std::string& channel)
{
    for(const auto& entry: cChannels)
    {
        if(entry.first == channel)
        {
            return entry.second;
        }
    }
    return 0;
}

class Receiver
{
public:
    Receiver(RtlSdrDevice& device, void* radio)
        : device_(device)
        , radio_(radio)
    {
    }

    bool tune(const std::string& channel)
    {
        {
            std::lock_guard<std::mutex> lock(gState.mutex);
            gState.generation++;
            gState.channel = channel;
            gState.timeSynced = false;
            gState.syncReported = false;
            gState.ensembleKnown = false;
            gState.ensembleLabel.clear();
            gState.ensembleId = 0;
            gState.names.clear();
            gState.playing = 0;
        }
        reported_.clear();
        ensembleSent_ = false;
        eccSent_ = 0;
        selected_ = false;
        dabReset_msc(radio_);
        device_.stopReader();
        const int frequency = channelFrequency(channel);
        if(!device_.restartReader(frequency * 1000))
        {
            fail("device", "cannot tune to " + channel);
            return false;
        }
        dabReset(radio_);
        gEvents.send(Json("tuned").add("channel", channel).add("frequency", frequency));
        return true;
    }

    bool synced()
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        return gState.timeSynced;
    }

    bool ensembleKnown()
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        return gState.ensembleKnown;
    }

    // reports the ensemble and new services; returns the number of new services
    int update(const std::string& channel)
    {
        std::string label;
        uint32_t id = 0;
        bool known = false;
        std::map<uint32_t, std::string> names;
        {
            std::lock_guard<std::mutex> lock(gState.mutex);
            label = gState.ensembleLabel;
            id = gState.ensembleId;
            known = gState.ensembleKnown;
            names = gState.names;
        }
        const int ecc = static_cast<dabProcessor*>(radio_)->get_ecc();
        if(known && (!ensembleSent_ || (ecc != 0 && ecc != eccSent_)))
        {
            ensembleSent_ = true;
            eccSent_ = ecc;
            gEvents.send(Json("ensemble").add("channel", channel).add("id", hex(id, 4)).add("label", label)
                             .add("ecc", ecc != 0 ? hex(static_cast<uint32_t>(ecc), 2) : std::string()));
        }
        int added = 0;
        for(const auto& [sid, name]: names)
        {
            if(reported_.count(sid) != 0 || name.empty())
            {
                continue;
            }
            Json json("service");
            json.add("channel", channel).add("sid", sidKey(sid)).add("label", name);
            if(is_audioService(radio_, name))
            {
                audiodata data;
                data.defined = false;
                dataforAudioService(radio_, name, data, 0);
                if(!data.defined)
                {
                    continue;  // the service component (FIG 0/2) is not there yet
                }
                json.add("shortLabel", trim(data.shortName)).add("audio", true)
                    .add("dabPlus", data.ASCTy == 077).add("bitrate", static_cast<int>(data.bitRate));
            }
            else if(is_dataService(radio_, name))
            {
                json.add("audio", false);
            }
            else
            {
                continue;
            }
            reported_.insert(sid);
            gEvents.send(json);
            ++added;
        }
        return added;
    }

    // starts the service once the ensemble carries it
    void select(uint32_t sid)
    {
        if(selected_)
        {
            return;
        }
        std::string name;
        {
            std::lock_guard<std::mutex> lock(gState.mutex);
            const auto found = gState.names.find(sid);
            if(found == gState.names.end())
            {
                return;
            }
            name = found->second;
        }
        if(!is_audioService(radio_, name))
        {
            return;
        }
        audiodata data;
        data.defined = false;
        dataforAudioService(radio_, name, data, 0);
        if(!data.defined)
        {
            return;
        }
        dabReset_msc(radio_);
        {
            std::lock_guard<std::mutex> lock(gState.mutex);
            gState.playing = sid;
        }
        set_audioChannel(radio_, data);
        selected_ = true;
        gEvents.send(Json("playing").add("sid", sidKey(sid)).add("label", name)
                         .add("dabPlus", data.ASCTy == 077).add("bitrate", static_cast<int>(data.bitRate)));
    }

private:
    RtlSdrDevice& device_;
    void* radio_;
    std::set<uint32_t> reported_;
    bool ensembleSent_ = false;
    int eccSent_ = 0;
    bool selected_ = false;
};

bool sleepFor(double seconds)
{
    const auto until = Clock::now() + std::chrono::milliseconds(static_cast<int>(seconds * 1000));
    while(Clock::now() < until)
    {
        if(gStop.load())
        {
            return false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    return !gStop.load();
}

double since(Clock::time_point start)
{
    return std::chrono::duration<double>(Clock::now() - start).count();
}

// --- modes ----------------------------------------------------------------------------------

int play(Receiver& receiver, RtlSdrDevice& device)
{
    if(!receiver.tune(gOptions.channel))
    {
        return 3;
    }
    bool synced = false;
    bool reported = false;
    const auto start = Clock::now();
    while(!gStop.load())
    {
        if(device.lost())
        {
            fail("device-lost", "The RTL-SDR stick was removed");
            return 3;
        }
        const bool now = receiver.synced();
        if(now != synced || (!reported && since(start) > gOptions.syncSeconds))
        {
            synced = now;
            reported = true;
            gEvents.send(Json("sync").add("channel", gOptions.channel).add("synced", synced));
        }
        receiver.update(gOptions.channel);
        if(gOptions.service != 0)
        {
            receiver.select(gOptions.service);
        }
        sleepFor(0.2);
    }
    return 0;
}

int scan(Receiver& receiver, RtlSdrDevice& device)
{
    std::vector<std::string> channels = gOptions.channels;
    if(channels.empty())
    {
        for(const auto& entry: cChannels)
        {
            channels.push_back(entry.first);
        }
    }
    int total = 0;
    int withEnsemble = 0;
    for(size_t index = 0; index < channels.size() && !gStop.load(); ++index)
    {
        const std::string& channel = channels[index];
        gEvents.send(Json("scan").add("channel", channel).add("index", static_cast<int>(index))
                         .add("total", static_cast<int>(channels.size())).add("found", total));
        if(!receiver.tune(channel))
        {
            return 3;
        }
        const auto start = Clock::now();
        // time sync (a DAB signal at all), then the ensemble, then services until the list stays the same
        while(!gStop.load() && !receiver.synced() && since(start) < gOptions.syncSeconds)
        {
            sleepFor(0.1);
        }
        int found = 0;
        bool ensemble = false;
        if(receiver.synced())
        {
            auto lastNew = Clock::now();
            while(!gStop.load() && since(start) < gOptions.scanSeconds)
            {
                if(device.lost())
                {
                    fail("device-lost", "The RTL-SDR stick was removed");
                    return 3;
                }
                const int added = receiver.update(channel);
                ensemble = ensemble || receiver.ensembleKnown();
                if(added > 0)
                {
                    found += added;
                    lastNew = Clock::now();
                }
                // no ensemble 4 s after the sync: no DAB here; labels: 2 s without a new one
                if(!ensemble && since(start) > gOptions.syncSeconds + 4)
                {
                    break;
                }
                if(ensemble && found > 0 && since(lastNew) > 2.0)
                {
                    break;
                }
                sleepFor(0.2);
            }
        }
        if(ensemble)
        {
            ++withEnsemble;
        }
        total += found;
        gEvents.send(Json("channel").add("channel", channel).add("ensemble", ensemble).add("services", found));
    }
    gEvents.send(Json("done").add("complete", !gStop.load()).add("ensembles", withEnsemble).add("services", total));
    return 0;
}

// --- command line -----------------------------------------------------------------------------

void usage(FILE* out)
{
    std::fprintf(out,
        "Usage: openhu-dab --channel CH [--service SID] [options]\n"
        "       openhu-dab --scan [--channels CH,CH,...] [options]\n"
        "\n"
        "DAB/DAB+ receiver for an RTL-SDR stick (Band III, 5A-13F), for the OpenHU radio plugin.\n"
        "Audio: raw PCM (s16le, 2 channels, --rate) on stdout. Events: JSON lines on stderr or --events-fd.\n"
        "No network listener.\n"
        "\n"
        "  -c, --channel CH       Band III channel to tune (e.g. 7A)\n"
        "  -s, --service SID      service to play, hex (e.g. 0xD882)\n"
        "      --scan             scan all channels (or --channels), then exit\n"
        "      --channels LIST    channels for --scan, comma separated\n"
        "      --sync-seconds N   time to find a DAB signal on a channel (default 3)\n"
        "      --scan-seconds N   at most this long per channel with a signal (default 10)\n"
        "  -d, --device N         RTL-SDR device index (default 0)\n"
        "  -g, --gain DB          tuner gain in dB, or \"auto\" (default)\n"
        "  -p, --ppm N            frequency correction in ppm\n"
        "  -T, --bias-tee         antenna power on (RTL-SDR Blog V3/V4 and compatible)\n"
        "      --events-fd N      write the events to this file descriptor (default 2, stderr)\n"
        "      --slides DIR       write slideshow pictures to DIR (default: base64 in the event)\n"
        "      --rate N           output sample rate (default 48000, 0: the service's own rate)\n"
        "  -V, --version          print the version\n"
        "  -h, --help             this help\n"
        "\n"
        "Events: device, tuned, sync, ensemble, service, playing, audio, dls, slide, signal, scan, channel,\n"
        "done, error {code, message}. Exit status: 0 done/stopped, 2 bad arguments, 3 device error.\n");
}

bool parseInt(const char* text, int& value)
{
    char* end = nullptr;
    errno = 0;
    const long parsed = std::strtol(text, &end, 0);
    if(errno != 0 || end == text || *end != '\0')
    {
        return false;
    }
    value = static_cast<int>(parsed);
    return true;
}

bool parseDouble(const char* text, double& value)
{
    char* end = nullptr;
    value = std::strtod(text, &end);
    return end != text && *end == '\0' && value >= 0;
}

std::string upper(std::string text)
{
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) { return std::toupper(c); });
    return trim(text);
}

int parseArguments(int argc, char** argv)
{
    enum { kScan = 1000, kChannels, kSync, kScanSeconds, kEventsFd, kSlides, kRate };
    static const option longOptions[] = {
        {"channel", required_argument, nullptr, 'c'},
        {"service", required_argument, nullptr, 's'},
        {"scan", no_argument, nullptr, kScan},
        {"channels", required_argument, nullptr, kChannels},
        {"sync-seconds", required_argument, nullptr, kSync},
        {"scan-seconds", required_argument, nullptr, kScanSeconds},
        {"device", required_argument, nullptr, 'd'},
        {"gain", required_argument, nullptr, 'g'},
        {"ppm", required_argument, nullptr, 'p'},
        {"bias-tee", no_argument, nullptr, 'T'},
        {"events-fd", required_argument, nullptr, kEventsFd},
        {"slides", required_argument, nullptr, kSlides},
        {"rate", required_argument, nullptr, kRate},
        {"version", no_argument, nullptr, 'V'},
        {"help", no_argument, nullptr, 'h'},
        {nullptr, 0, nullptr, 0},
    };
    int option = 0;
    while((option = getopt_long(argc, argv, "c:s:d:g:p:TVh", longOptions, nullptr)) != -1)
    {
        double number = 0;
        switch(option)
        {
        case 'c':
            gOptions.channel = upper(optarg);
            if(channelFrequency(gOptions.channel) == 0)
            {
                std::fprintf(stderr, "openhu-dab: unknown channel %s (Band III: 5A-13F)\n", optarg);
                return 2;
            }
            break;
        case 's':
        {
            char* end = nullptr;
            const unsigned long sid = std::strtoul(optarg, &end, 16);
            if(end == optarg || *end != '\0' || sid == 0 || sid > 0xFFFFFFFFul)
            {
                std::fprintf(stderr, "openhu-dab: bad service id %s\n", optarg);
                return 2;
            }
            gOptions.service = static_cast<uint32_t>(sid);
            break;
        }
        case kScan:
            gOptions.scan = true;
            break;
        case kChannels:
        {
            std::stringstream list(optarg);
            std::string item;
            while(std::getline(list, item, ','))
            {
                item = upper(item);
                if(item.empty())
                {
                    continue;
                }
                if(channelFrequency(item) == 0)
                {
                    std::fprintf(stderr, "openhu-dab: unknown channel %s (Band III: 5A-13F)\n", item.c_str());
                    return 2;
                }
                gOptions.channels.push_back(item);
            }
            break;
        }
        case kSync:
            if(!parseDouble(optarg, gOptions.syncSeconds)) return 2;
            break;
        case kScanSeconds:
            if(!parseDouble(optarg, gOptions.scanSeconds)) return 2;
            break;
        case 'd':
            if(!parseInt(optarg, gOptions.device) || gOptions.device < 0) return 2;
            break;
        case 'g':
            if(std::strcmp(optarg, "auto") == 0)
            {
                gOptions.gain = -1;
            }
            else if(parseDouble(optarg, number))
            {
                gOptions.gain = static_cast<int>(number * 10 + 0.5);
            }
            else
            {
                std::fprintf(stderr, "openhu-dab: bad gain %s (dB or auto)\n", optarg);
                return 2;
            }
            break;
        case 'p':
            if(!parseInt(optarg, gOptions.ppm)) return 2;
            break;
        case 'T':
            gOptions.biasTee = true;
            break;
        case kEventsFd:
            if(!parseInt(optarg, gOptions.eventsFd) || fcntl(gOptions.eventsFd, F_GETFD) < 0)
            {
                std::fprintf(stderr, "openhu-dab: --events-fd %s is not open\n", optarg);
                return 2;
            }
            break;
        case kSlides:
            gOptions.slides = optarg;
            break;
        case kRate:
            if(!parseInt(optarg, gOptions.rate) || gOptions.rate < 0 || (gOptions.rate > 0 && gOptions.rate < 8000)
               || gOptions.rate > 192000)
            {
                std::fprintf(stderr, "openhu-dab: bad rate %s\n", optarg);
                return 2;
            }
            break;
        case 'V':
            std::printf("openhu-dab %s (dab-cmdline %s)\n", OPENHU_DAB_VERSION, DAB_CMDLINE_VERSION);
            return 0;
        case 'h':
            usage(stdout);
            return 0;
        default:
            usage(stderr);
            return 2;
        }
    }
    if(optind < argc)
    {
        std::fprintf(stderr, "openhu-dab: unexpected argument %s\n", argv[optind]);
        return 2;
    }
    if(gOptions.scan == !gOptions.channel.empty())
    {
        std::fprintf(stderr, "openhu-dab: either --channel or --scan\n");
        usage(stderr);
        return 2;
    }
    if(!gOptions.slides.empty())
    {
        struct stat info{};
        if(::stat(gOptions.slides.c_str(), &info) != 0 || !S_ISDIR(info.st_mode))
        {
            std::fprintf(stderr, "openhu-dab: --slides %s is no directory\n", gOptions.slides.c_str());
            return 2;
        }
    }
    return -1;
}

}

int main(int argc, char** argv)
{
    // ends with the radio plugin, like the tools it starts with radiolib.spawn
    prctl(PR_SET_PDEATHSIG, SIGTERM);

    const int status = parseArguments(argc, argv);
    if(status >= 0)
    {
        return status;
    }
    gEvents.setFd(gOptions.eventsFd);

    // stdout carries the PCM; the library prints to stdout here and there, so fd 1 becomes stderr
    std::fflush(stdout);
    const int pcmFd = ::dup(STDOUT_FILENO);
    ::dup2(STDERR_FILENO, STDOUT_FILENO);
    if(pcmFd < 0)
    {
        fail("pcm", std::strerror(errno));
        return 3;
    }
    ::fcntl(pcmFd, F_SETFD, FD_CLOEXEC);

    struct sigaction action{};
    action.sa_handler = onSignal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, nullptr);
    sigaction(SIGINT, &action, nullptr);
    sigaction(SIGHUP, &action, nullptr);
    signal(SIGPIPE, SIG_IGN);

    RtlSdrDevice* device = nullptr;
    try
    {
        device = new RtlSdrDevice(gOptions.device, gOptions.ppm, gOptions.gain, gOptions.biasTee);
    }
    catch(const DeviceError& error)
    {
        fail(error.code, error.what());
        return 3;
    }
    gEvents.send(Json("device").add("name", device->name()).add("gain", device->gain())
                     .add("biasTee", gOptions.biasTee).add("version", OPENHU_DAB_VERSION));

    AudioOutput audio(pcmFd, gOptions.rate);
    if(!gOptions.scan)
    {
        gAudio = &audio;
    }

    API_struct interface{};
    interface.dabMode = 1;
    interface.thresholdValue = 6;
    interface.syncsignal_Handler = syncSignal;
    interface.systemdata_Handler = systemData;
    interface.name_of_ensemble = ensembleName;
    interface.serviceName = serviceName;
    interface.fib_quality_Handler = ficQuality;
    interface.audioOut_Handler = audioOut;
    interface.dataOut_Handler = dynamicLabel;
    interface.bytesOut_Handler = nullptr;
    interface.programdata_Handler = nullptr;
    interface.program_quality_Handler = nullptr;
    interface.motdata_Handler = motData;
    interface.tii_data_Handler = nullptr;
    interface.timeHandler = nullptr;
    void* radio = dabInit(device, &interface, nullptr, nullptr, nullptr);
    if(radio == nullptr)
    {
        fail("library", "the DAB library could not start");
        delete device;
        return 3;
    }
    dabStartProcessing(radio);

    Receiver receiver(*device, radio);
    const int result = gOptions.scan ? scan(receiver, *device) : play(receiver, *device);

    // clean shutdown: reader first (no new samples), then the library, then the stick
    device->stopReader();
    dabStop(radio);
    dabExit(radio);
    gAudio = nullptr;
    delete device;
    {
        std::lock_guard<std::mutex> lock(gState.mutex);
        for(const auto& path: gState.slideFiles)
        {
            std::remove(path.c_str());
        }
    }
    return result;
}
