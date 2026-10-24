import CoreAudio
import Foundation
import Darwin

private let outputQueue = DispatchQueue(label: "com.talktrack.audio-output", qos: .userInitiated)
private let outputCondition = NSCondition()
private var queuedAudio: [Data] = []
private var outputFinished = false
private let maxQueuedBuffers = 128

private var processTapID = AudioObjectID(kAudioObjectUnknown)
private var aggregateDeviceID = AudioObjectID(kAudioObjectUnknown)
private var ioProcID: AudioDeviceIOProcID?

private func report(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

private func check(_ status: OSStatus, _ operation: String) throws {
    guard status == noErr else {
        throw NSError(domain: NSOSStatusErrorDomain, code: Int(status), userInfo: [
            NSLocalizedDescriptionKey: "\(operation) failed (Core Audio status \(status))"
        ])
    }
}

private func enqueueAudio(_ data: Data) {
    outputCondition.lock()
    if queuedAudio.count < maxQueuedBuffers {
        queuedAudio.append(data)
        outputCondition.signal()
    }
    outputCondition.unlock()
}

private func startOutputWriter() {
    outputQueue.async {
        while true {
            outputCondition.lock()
            while queuedAudio.isEmpty && !outputFinished {
                outputCondition.wait()
            }
            if queuedAudio.isEmpty && outputFinished {
                outputCondition.unlock()
                break
            }
            let next = queuedAudio.removeFirst()
            outputCondition.unlock()
            do {
                try FileHandle.standardOutput.write(contentsOf: next)
            } catch {
                report("Audio output pipe closed: \(error)")
                outputCondition.lock()
                outputFinished = true
                queuedAudio.removeAll()
                outputCondition.broadcast()
                outputCondition.unlock()
                break
            }
        }
    }
}

private func finishOutputWriter() {
    outputCondition.lock()
    outputFinished = true
    outputCondition.broadcast()
    outputCondition.unlock()
    outputQueue.sync {}
}

private func writeStreamHeader(sampleRate: Double, channels: UInt16, bits: UInt16) throws {
    var rate = UInt32(sampleRate.rounded()).littleEndian
    var littleChannels = channels.littleEndian
    var littleBits = bits.littleEndian
    var header = Data("TTCA".utf8)
    withUnsafeBytes(of: &rate) { header.append(contentsOf: $0) }
    withUnsafeBytes(of: &littleChannels) { header.append(contentsOf: $0) }
    withUnsafeBytes(of: &littleBits) { header.append(contentsOf: $0) }
    try FileHandle.standardOutput.write(contentsOf: header)
}

private func startCapture() throws {
    let description = CATapDescription(monoGlobalTapButExcludeProcesses: [])
    description.name = "TalkTrack System Audio"
    description.uuid = UUID()
    description.isPrivate = true
    description.muteBehavior = .unmuted

    try check(AudioHardwareCreateProcessTap(description, &processTapID), "Create process tap")

    var formatAddress = AudioObjectPropertyAddress(
        mSelector: kAudioTapPropertyFormat,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var format = AudioStreamBasicDescription()
    var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    try check(
        AudioObjectGetPropertyData(processTapID, &formatAddress, 0, nil, &formatSize, &format),
        "Read process tap format"
    )
    guard format.mBitsPerChannel == 32,
          format.mFormatFlags & kAudioFormatFlagIsFloat != 0 else {
        throw NSError(domain: "TalkTrackAudioTap", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "Core Audio tap did not provide 32-bit floating-point audio"
        ])
    }

    let aggregateDescription: [String: Any] = [
        kAudioAggregateDeviceNameKey: "TalkTrack System Audio",
        kAudioAggregateDeviceUIDKey: "com.talktrack.audio-tap.\(UUID().uuidString)",
        kAudioAggregateDeviceIsPrivateKey: true,
        kAudioAggregateDeviceIsStackedKey: false,
        kAudioAggregateDeviceTapListKey: [[
            kAudioSubTapUIDKey: description.uuid.uuidString,
            kAudioSubTapDriftCompensationKey: true,
        ]],
    ]
    try check(
        AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregateDeviceID),
        "Create aggregate audio device"
    )

    let ioQueue = DispatchQueue(label: "com.talktrack.core-audio-tap", qos: .userInteractive)
    try check(
        AudioDeviceCreateIOProcIDWithBlock(&ioProcID, aggregateDeviceID, ioQueue) {
            _, inputData, _, _, _ in
            let buffers = UnsafeMutableAudioBufferListPointer(
                UnsafeMutablePointer(mutating: inputData)
            )
            guard buffers.count == 1,
                  let bytes = buffers[0].mData,
                  buffers[0].mDataByteSize > 0 else { return }
            enqueueAudio(Data(bytes: bytes, count: Int(buffers[0].mDataByteSize)))
        },
        "Create aggregate device input callback"
    )
    try check(AudioDeviceStart(aggregateDeviceID, ioProcID), "Start system audio capture")
    try writeStreamHeader(
        sampleRate: format.mSampleRate,
        channels: UInt16(format.mChannelsPerFrame),
        bits: UInt16(format.mBitsPerChannel)
    )
    startOutputWriter()
}

private func stopCapture() {
    if aggregateDeviceID != AudioObjectID(kAudioObjectUnknown) {
        if let ioProcID {
            _ = AudioDeviceStop(aggregateDeviceID, ioProcID)
            _ = AudioDeviceDestroyIOProcID(aggregateDeviceID, ioProcID)
        }
        _ = AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
    }
    if processTapID != AudioObjectID(kAudioObjectUnknown) {
        _ = AudioHardwareDestroyProcessTap(processTapID)
    }
    finishOutputWriter()
}

private var terminationSource: DispatchSourceSignal?

private func installSignalHandlers() {
    signal(SIGTERM, SIG_IGN)
    signal(SIGINT, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    source.setEventHandler {
        stopCapture()
        exit(0)
    }
    source.resume()
    terminationSource = source
}

do {
    installSignalHandlers()
    try startCapture()
    dispatchMain()
} catch {
    report("TalkTrack system audio capture failed: \(error.localizedDescription)")
    stopCapture()
    exit(1)
}
