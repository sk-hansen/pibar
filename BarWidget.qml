import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "skh.pibar"

  // ---- Plan usage (fetched here so the bar label updates without the panel).
  property var usage: null
  readonly property var usageLimits: usage && usage.ok ? usage.limits : []
  readonly property int sessionPct: usageLimits.length > 0 ? usageLimits[0].pct : -1
  readonly property int maxPct: {
    var m = -1
    for (var i = 0; i < usageLimits.length; i++)
      if (usageLimits[i].pct > m) m = usageLimits[i].pct
    return m
  }

  function refreshUsage() {
    if (!usageProc.running) usageProc.running = true
  }

  Timer {
    interval: 300000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshUsage()
  }

  Timer {
    id: usageDeadline
    interval: 15000
    onTriggered: if (usageProc.running) usageProc.running = false
  }

  Process {
    id: usageProc
    command: ["python3", Qt.resolvedUrl("usage").toString().replace(/^file:\/\//, "")]
    onRunningChanged: running ? usageDeadline.restart() : usageDeadline.stop()
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text.length > 65536) return
        try { root.usage = JSON.parse(text) } catch (e) { root.usage = null }
      }
    }
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onStatusChanged: if (status === Loader.Error) console.warn("skh.pibar Panel.qml failed to load")
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    readonly property string piGlyph: String.fromCodePoint(0xF06A9)  // nf-md-robot
    text: root.sessionPct >= 0 ? piGlyph + " " + root.sessionPct + "%" : piGlyph
    active: root.maxPct >= 90
    fontSize: Style.font.caption
    tooltipText: root.usage && root.usage.ok
      ? root.usageLimits.map(l => ((l.provider || "claude") !== "claude"
          ? l.provider.charAt(0).toUpperCase() + l.provider.slice(1) + " " : "")
          + l.name + " " + l.pct + "%").join(" · ")
        + (root.usage.stale ? " · stale" : "")
      : (root.usage && root.usage.error ? root.usage.error : "Pi Bar — usage & sessions")

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.refreshUsage()
      else root.togglePanel()
    }
  }
}
