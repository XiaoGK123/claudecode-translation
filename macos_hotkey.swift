import AppKit
import ApplicationServices
import Carbon

// The event tap observes keys only to recognize Option+A; it never logs typing.
var busy = false
var finishing = false
var task: Process?
var tap: CFMachPort?
var originalText: String?
var target: AXUIElement?
var targetPID: pid_t = 0
var targetWindow: AXUIElement?
var interactionChanged = false
let generatedEventTag: Int64 = 0x43545452414e53
var sources: [DispatchSourceSignal] = []
let clipboard = NSPasteboard.general
var savedClipboard: [[NSPasteboard.PasteboardType: Data]] = []
var ownedClipboardCount = 0

func focused() -> AXUIElement? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute as CFString, &result) == .success,
          let value = result, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
    return (value as! AXUIElement)
}

func sameFocus() -> Bool {
    guard !interactionChanged,
          NSWorkspace.shared.frontmostApplication?.processIdentifier == targetPID else { return false }
    if let oldWindow = targetWindow, let currentWindow = focusedWindow(targetPID), !CFEqual(oldWindow, currentWindow) {
        return false
    }
    if let old = target, let current = focused() { return CFEqual(current, old) }
    // Some web input controls expose neither selected text nor an AX editor.
    // In that case app/window identity and user-interaction cancellation guard paste.
    return true
}

func focusedWindow(_ pid: pid_t) -> AXUIElement? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(pid), kAXFocusedWindowAttribute as CFString, &result) == .success,
          let value = result, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
    return (value as! AXUIElement)
}

func secure(_ element: AXUIElement?) -> Bool {
    if IsSecureEventInputEnabled() { return true }
    guard let element = element else { return false }
    var subrole: CFTypeRef?
    AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &subrole)
    return subrole as? String == kAXSecureTextFieldSubrole
}

func key(_ code: CGKeyCode) {
    for down in [true, false] {
        let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down)
        event?.flags = .maskCommand
        event?.setIntegerValueField(.eventSourceUserData, value: generatedEventTag)
        event?.post(tap: .cghidEventTap)
    }
}

func saveClipboard() {
    savedClipboard = (clipboard.pasteboardItems ?? []).map { item in
        var values: [NSPasteboard.PasteboardType: Data] = [:]
        for type in item.types { if let data = item.data(forType: type) { values[type] = data } }
        return values
    }
}

func restoreClipboard() {
    // Don't overwrite a new clipboard item copied by the user during translation.
    guard clipboard.changeCount == ownedClipboardCount else { return }
    clipboard.clearContents()
    let items = savedClipboard.map { values -> NSPasteboardItem in
        let item = NSPasteboardItem()
        for (type, data) in values { item.setData(data, forType: type) }
        return item
    }
    clipboard.writeObjects(items)
}

func diagnostic(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    NSSound.beep()
}

func finish(_ replacement: String?) {
    guard !finishing else { return }
    finishing = true
    guard let original = originalText else { busy = false; return }
    if sameFocus() && clipboard.changeCount == ownedClipboardCount {
        clipboard.clearContents()
        clipboard.setString(replacement ?? original, forType: .string)
        ownedClipboardCount = clipboard.changeCount
        key(9) // Command+V, no Enter: leave the draft for the user to submit.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            restoreClipboard()
            originalText = nil
            busy = false
        }
    } else {
        // Leave source text for manual recovery; never paste into another field.
        if clipboard.changeCount == ownedClipboardCount {
            clipboard.clearContents()
            clipboard.setString(original, forType: .string)
        }
        diagnostic("输入焦点或剪贴板已改变，未自动粘贴。请在原输入框撤销剪切，或从剪贴板恢复原文。")
        originalText = nil
        busy = false
    }
}

func translateSelection(_ text: String) {
    originalText = text
    let beforeCut = clipboard.changeCount
    key(7) // Command+X
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
        if !interactionChanged { ownedClipboardCount = clipboard.changeCount }
        guard sameFocus() else { finish(nil); return }
        var selected: CFTypeRef?
        if let element = target,
           AXUIElementCopyAttributeValue(element, kAXSelectedTextAttribute as CFString, &selected) == .success,
           let remaining = selected as? String, !remaining.isEmpty {
            // Cut was rejected: do not paste a duplicate into a read-only control.
            originalText = nil
            restoreClipboard()
            busy = false
            diagnostic("输入框未执行剪切，原内容保持不变。")
            return
        }
        if clipboard.changeCount == beforeCut {
            originalText = nil
            restoreClipboard()
            busy = false
            diagnostic("未确认剪切成功，未翻译或粘贴；请确认光标在输入框中。")
            return
        }
        let process = Process()
        task = process
        process.executableURL = URL(fileURLWithPath: CommandLine.arguments[1])
        process.arguments = [CommandLine.arguments[2]]
        let input = Pipe(), output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        do {
            try process.run()
        } catch {
            diagnostic("无法启动翻译程序，恢复原文。")
            finish(nil)
            return
        }
        DispatchQueue.global().async {
            input.fileHandleForWriting.write(Data(text.utf8))
            try? input.fileHandleForWriting.close()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            DispatchQueue.main.async {
                task = nil
                if process.terminationStatus != 0 { diagnostic("翻译失败，恢复原文。") }
                let result = process.terminationStatus == 0 ? String(data: data, encoding: .utf8) : nil
                finish(result)
            }
        }
    }
}

func copied(_ previousCount: Int, fallback: Bool) {
    guard sameFocus() else { restoreClipboard(); busy = false; return }
    if clipboard.changeCount != previousCount, let text = clipboard.string(forType: .string), !text.isEmpty {
        ownedClipboardCount = clipboard.changeCount
        translateSelection(text)
        return
    }
    if fallback {
        ownedClipboardCount = clipboard.changeCount
        restoreClipboard()
        diagnostic("未取得可编辑文本，未执行翻译。")
        busy = false
        return
    }
    key(0) // Command+A, only after selection copy found no text.
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
        guard sameFocus() else { restoreClipboard(); busy = false; return }
        let count = clipboard.changeCount
        key(8)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { copied(count, fallback: true) }
    }
}

func activate() {
    guard !busy else { return }
    let element = focused()
    guard !secure(element), let app = NSWorkspace.shared.frontmostApplication else {
        diagnostic("当前处于安全输入状态，未读取或剪切文本。")
        return
    }
    busy = true
    finishing = false
    target = element
    targetPID = app.processIdentifier
    targetWindow = focusedWindow(targetPID)
    interactionChanged = false
    saveClipboard()
    ownedClipboardCount = clipboard.changeCount
    var selected: CFTypeRef?
    if let element = element,
       AXUIElementCopyAttributeValue(element, kAXSelectedTextAttribute as CFString, &selected) == .success,
       let selection = selected as? String {
        if !selection.isEmpty {
            translateSelection(selection)
        } else {
            selectAllAndCopy()
        }
        return
    }
    // Fall back to standard copy semantics when AX selection isn't exposed.
    let count = clipboard.changeCount
    key(8)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { copied(count, fallback: false) }
}

func selectAllAndCopy() {
    key(0)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
        guard sameFocus() else { busy = false; return }
        let count = clipboard.changeCount
        key(8)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { copied(count, fallback: true) }
    }
}

if CommandLine.arguments.contains("--check") {
    print("macOS hotkey helper compiled; Option+A uses key code 0 and Option modifier")
    print("Accessibility permission: \(AXIsProcessTrusted() ? "granted" : "missing")")
    exit(0)
}
guard CommandLine.arguments.count == 3 else { exit(1) }
let trustOptions = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
guard AXIsProcessTrustedWithOptions(trustOptions) else {
    print("已向 macOS 申请辅助功能权限，请在系统授权提示中打开设置并允许，然后重启服务。")
    fflush(stdout)
    exit(2)
}
let callback: CGEventTapCallBack = { _, type, event, _ in
    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        if let current = tap { CGEvent.tapEnable(tap: current, enable: true) }
        return Unmanaged.passUnretained(event)
    }
    if event.getIntegerValueField(.eventSourceUserData) == generatedEventTag {
        return Unmanaged.passUnretained(event)
    }
    let modifiers = event.flags.intersection([.maskAlternate, .maskCommand, .maskControl, .maskShift])
    if type == .keyDown && event.getIntegerValueField(.keyboardEventKeycode) == 0 && modifiers == .maskAlternate {
        DispatchQueue.main.async { activate() }
        return nil
    }
    if busy && (type == .keyDown || type == .leftMouseDown || type == .rightMouseDown || type == .otherMouseDown || type == .scrollWheel) {
        interactionChanged = true
    }
    return Unmanaged.passUnretained(event)
}
let monitoredEvents: [CGEventType] = [.keyDown, .leftMouseDown, .rightMouseDown, .otherMouseDown, .scrollWheel]
let eventMask = monitoredEvents.reduce(CGEventMask(0)) { $0 | CGEventMask(1 << $1.rawValue) }
tap = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap, options: .defaultTap,
                        eventsOfInterest: eventMask,
                        callback: callback, userInfo: nil)
guard let eventTap = tap else {
    print("无法注册 Option+A：请检查辅助功能/输入监控权限后重启。")
    fflush(stdout)
    exit(2)
}
CFRunLoopAddSource(CFRunLoopGetMain(), CFMachPortCreateRunLoopSource(nil, eventTap, 0), .commonModes)
CGEvent.tapEnable(tap: eventTap, enable: true)
for sig in [SIGTERM, SIGINT, SIGHUP] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler {
        task?.terminate()
        if originalText != nil { finish(nil) }
        CGEvent.tapEnable(tap: eventTap, enable: false)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { exit(0) }
    }
    source.resume()
    sources.append(source)
}
// Don't leave a global shortcut running if the Python service is killed.
let parentPID = getppid()
let parentMonitor = DispatchSource.makeTimerSource(queue: .main)
parentMonitor.schedule(deadline: .now() + 1, repeating: 1)
parentMonitor.setEventHandler {
    if getppid() != parentPID { kill(getpid(), SIGTERM) }
}
parentMonitor.resume()
print("Option+A 已注册")
fflush(stdout)
CFRunLoopRun()
