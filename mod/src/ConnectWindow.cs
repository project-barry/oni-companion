using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;

namespace OniCompanionLink
{
    /// <summary>
    /// The in-game "Connect a phone" window (plan 3.0 and 5.2). Opened from a button the mod adds to the pause menu (PauseScreen is a
    /// KModalButtonMenu whose ButtonInfo list is rebuilt by its private ConfigureButtonInfos; a postfix appends one entry, so the
    /// game's own button prefab draws it). Pause is the right place: the window needs the game running (the service starts with the
    /// game's first mod write), and the menu is modal and already pauses the game.
    /// Files only: reads companion/pairing/state.json (FileSystemWatcher sets a flag; no polling), writes
    /// companion/pairing/requests/req-N.json atomically. It opens no network connection and starts no process.
    /// Style: every piece is a clone of the game's own pause-screen pieces (title LocText, menu button prefab) and the colors of its own
    /// ColorStyleSettings, so fonts and buttons are the game's. Built in small timed steps (at most ~1.5 ms per frame, logged when over 2 ms),
    /// then only changed values are written, once per state change; the code countdown changes one label per second while the window is open.
    /// </summary>
    internal static class ConnectWindow
    {
        private const double FrameBudgetMs = 1.5, LogOverMs = 2.0;
        private const int DeviceRows = 8;
        private const float PanelWidth = 820f;

        private static PairingFiles files;
        private static FileSystemWatcher watcher;
        private static volatile bool stateDirty = true;

        private static GameObject root;                 // the window; null = closed
        private static Queue<System.Action> steps;             // build steps still to run
        private static bool built;
        private static PairState state;                 // newest parsed state.json (null = none or unreadable)
        private static long pendingSeq; private static float pendingSince;
        private static string notice = "";
        private static string lastCountdown = "";
        private static float lastCountdownAt;
        private static double worstMs;

        // template pieces, cloned from the pause screen
        private static GameObject buttonPrefab; private static LocText textTemplate;
        private static Transform canvasParent;
        private static Color panelColor = new Color(0.14f, 0.16f, 0.24f, 1f), headerColor = new Color(0.43f, 0.19f, 0.36f, 1f);

        // widgets
        private static LocText nameText, switchLabel, statusText, codeText, expiryText, addrText, devHeader, plainNote, offNote;
        private static KButton switchButton, newCodeButton, plainButton, resetButton, closeButton;
        private static LocText switchBtnText, plainBtnText;
        private static GameObject onSection;
        private static RawImage qrImage; private static Texture2D qrTex; private static string qrShown;
        private sealed class DevRow { public GameObject Go; public LocText Text; public KButton Remove; public string DeviceId; }
        private static readonly List<DevRow> rows = new List<DevRow>();

        // ---------------------------------------------------------------- start / entry point

        public static void Start()
        {
            try
            {
                files = new PairingFiles(Env.UserCompanionDir());
                Directory.CreateDirectory(files.RequestsDir);
                FileSystemWatcher w = new FileSystemWatcher(files.Dir, "state.json");
                w.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
                FileSystemEventHandler h = delegate (object s, FileSystemEventArgs e) { stateDirty = true; };
                w.Created += h; w.Changed += h; w.Deleted += h;
                w.Renamed += delegate (object s, RenamedEventArgs e) { stateDirty = true; };
                w.Error += delegate (object s, ErrorEventArgs e) { stateDirty = true; };
                w.EnableRaisingEvents = true;
                watcher = w;
            }
            catch (Exception e) { Log.Error("connect window: pairing folder not watched", e); }
        }

        public static void Stop()
        {
            try { FileSystemWatcher w = watcher; watcher = null; if (w != null) { w.EnableRaisingEvents = false; w.Dispose(); } } catch { }
            Close();
        }

        /// <summary>Postfix of PauseScreen.ConfigureButtonInfos: add "Connect a phone" after Options. Does nothing if the game's pieces are not found.</summary>
        public static void AddPauseButton(PauseScreen screen)
        {
            try
            {
                if (Env.Disabled || files == null) return;
                FieldInfo fb = typeof(KButtonMenu).GetField("buttons", BindingFlags.Instance | BindingFlags.NonPublic);
                IList<KButtonMenu.ButtonInfo> list = fb != null ? fb.GetValue(screen) as IList<KButtonMenu.ButtonInfo> : null;
                if (list == null) return;
                foreach (KButtonMenu.ButtonInfo b in list) if (b != null && b.text == ButtonText) return;     // already there
                List<KButtonMenu.ButtonInfo> n = new List<KButtonMenu.ButtonInfo>(list);
                KButtonMenu.ButtonInfo info = new KButtonMenu.ButtonInfo(ButtonText, global::Action.NumActions, delegate () { Open(screen); });
                int at = Math.Min(5, n.Count);       // after Resume, Save, Save as, Load, Options
                n.Insert(at, info);
                fb.SetValue(screen, n.ToArray());
            }
            catch (Exception e) { Log.Error("connect window: pause button", e); }
        }

        private const string ButtonText = "Connect a phone";

        // ---------------------------------------------------------------- open / close

        private static void Open(PauseScreen screen)
        {
            try
            {
                if (root != null) return;
                FieldInfo ft = typeof(PauseScreen).GetField("title", BindingFlags.Instance | BindingFlags.NonPublic);
                textTemplate = ft != null ? ft.GetValue(screen) as LocText : null;
                buttonPrefab = screen.buttonPrefab;
                canvasParent = screen.transform.parent;
                if (textTemplate == null || buttonPrefab == null || canvasParent == null) { Log.Warn("connect window: the pause screen's pieces were not found"); return; }
                ReadColors(screen);
                root = new GameObject("OniCompanionConnect", typeof(RectTransform));
                root.transform.SetParent(canvasParent, false);
                root.transform.SetAsLastSibling();
                root.SetActive(false);                  // shown when the build steps are done
                steps = new Queue<System.Action>();
                BuildSteps();
                built = false; state = null; stateDirty = true; notice = ""; pendingSeq = 0;  worstMs = 0;
            }
            catch (Exception e) { Log.Error("connect window: open", e); Close(); }
        }

        public static void Close()
        {
            try { if (root != null) UnityEngine.Object.Destroy(root); } catch { }
            root = null; built = false; steps = null; rows.Clear(); qrTex = null; qrShown = null; pendingSeq = 0;
            nameText = switchLabel = statusText = codeText = expiryText = addrText = devHeader = plainNote = offNote = switchBtnText = plainBtnText = null;
            switchButton = newCodeButton = plainButton = resetButton = closeButton = null; onSection = null; qrImage = null;
        }

        public static bool IsOpen { get { return root != null; } }

        // ---------------------------------------------------------------- per frame

        /// <summary>Game.Update postfix. Nothing happens while the window is closed.</summary>
        public static void Tick()
        {
            if (root == null) return;
            Stopwatch sw = Stopwatch.StartNew();
            try
            {
                PauseScreen ps = PauseScreen.Instance;
                if (ps == null || !ps.gameObject.activeInHierarchy) { Close(); return; }       // Escape or Resume closed the menu
                if (!built)
                {
                    while (steps.Count > 0 && sw.Elapsed.TotalMilliseconds < FrameBudgetMs) steps.Dequeue()();
                    if (steps.Count == 0) { built = true; root.SetActive(true); root.transform.SetAsLastSibling(); stateDirty = true; }
                }
                else
                {
                    bool changed = false;
                    if (stateDirty) { stateDirty = false; state = files.ReadState(); changed = true; AfterStateRead(); }
                    if (pendingSeq != 0 && Time.realtimeSinceStartup - pendingSince > PairingFiles.RequestMaxAgeSeconds + 2)
                    {
                        pendingSeq = 0; notice = "No answer. The service starts when the game is running. Try again in a few seconds."; changed = true;
                    }
                    if (changed) Refresh();
                    CountdownTick();
                }
            }
            catch (Exception e) { Log.Error("connect window tick", e); Close(); }
            double ms = sw.Elapsed.TotalMilliseconds;
            if (ms > worstMs) worstMs = ms;
            if (ms > LogOverMs) Log.Warn("connect window: a frame took " + ms.ToString("0.0", CultureInfo.InvariantCulture) + " ms (target 2 ms)");
        }

        private static void AfterStateRead()
        {
            if (state == null) return;
            if (pendingSeq != 0 && state.LastSeq >= pendingSeq)
            {
                if (state.LastSeq == pendingSeq && state.LastState == "failed") notice = string.IsNullOrEmpty(state.LastMessage) ? "That did not work." : state.LastMessage;
                else notice = "";
                pendingSeq = 0;
            }
        }

        // ---------------------------------------------------------------- actions (each writes one request file)

        private static void Send(string type, bool? enabled = null, string deviceId = null, bool? confirm = null)
        {
            try
            {
                long seq = files.WriteRequest(state, type, enabled, deviceId, confirm);
                pendingSeq = seq; pendingSince = Time.realtimeSinceStartup; notice = "Waiting for the service ...";
                Refresh();
            }
            catch (Exception e) { notice = "Could not write the request."; Log.Error("connect request " + type, e); Refresh(); }
        }

        private static void AskReset()
        {
            try
            {
                GameObject go = Util.KInstantiateUI(ScreenPrefabs.Instance.ConfirmDialogScreen.gameObject, canvasParent.gameObject, true);
                go.GetComponent<ConfirmDialogScreen>().PopupConfirmDialog(
                    "Reset identity? This gives the game a new name and a new key, and every paired phone has to pair again.",
                    delegate () { Send("reset_identity", null, null, true); }, delegate () { }, null, null, null, "Reset identity", "Cancel");
            }
            catch (Exception e) { Log.Error("connect window: reset dialog", e); }
        }

        // ---------------------------------------------------------------- showing the state

        private static void Refresh()
        {
            if (!built || root == null) return;
            PairState s = state;
            bool on = s != null && s.Enabled;
            nameText.text = s != null ? "This game is  " + s.Name + "   " + s.FingerprintTag : "No service answered yet";
            switchBtnText.text = pendingSeq != 0 ? "..." : (on ? "On" : "Off");
            switchButton.isInteractable = pendingSeq == 0;
            statusText.text = notice;
            onSection.SetActive(on);
            offNote.gameObject.SetActive(!on);
            offNote.text = s == null ? "The service starts when the game is running. Turn the switch on, then scan the code with the ONI Companion app."
                                      : "Switch on to show a code. Only a phone that pairs can see your colony.";
            if (on)
            {
                codeText.text = s.CodeDisplay ?? "";
                lastCountdown = ""; CountdownTick(true);
                SetQr(s.QrText);
                System.Text.StringBuilder a = new System.Text.StringBuilder();
                for (int i = 0; i < s.Addresses.Count; i++)
                    a.Append(s.AddressKinds[i] == "tailscale" ? "Tailscale  " : "Wi-Fi  ").Append(s.Addresses[i]).Append("   port ").Append(s.Port).Append('\n');
                if (s.Addresses.Count == 0) a.Append("No network address found.");
                addrText.text = a.ToString().TrimEnd('\n');
            }
            for (int i = 0; i < rows.Count; i++)
            {
                DevRow r = rows[i];
                if (s == null || i >= s.Devices.Count) { r.Go.SetActive(false); r.DeviceId = null; continue; }
                PairedDeviceInfo d = s.Devices[i];
                r.DeviceId = d.DeviceId;
                r.Text.text = d.Label + "   " + (d.Platform ?? "") + (d.Transport == "http" ? "   plain http" : "") + "   " + LastSeenText(d.LastSeen);
                r.Go.SetActive(true);
            }
            int count = s != null ? s.Devices.Count : 0;
            devHeader.text = count == 0 ? "No phone is paired yet." : (count > DeviceRows ? "Paired phones (first " + DeviceRows + " of " + count + ")" : "Paired phones");
            plainBtnText.text = s != null && s.PlainHttp ? "On" : "Off";
            plainButton.isInteractable = pendingSeq == 0 && s != null;
            string note = s != null && !string.IsNullOrEmpty(s.PlainHttpNote) ? s.PlainHttpNote : "For an iPhone in Safari. Plain http can be read by anyone on your Wi-Fi. Tailscale is safer.";
            plainNote.text = note;
            newCodeButton.isInteractable = pendingSeq == 0;
            resetButton.isInteractable = pendingSeq == 0 && s != null;
        }

        private static void CountdownTick(bool force = false)
        {
            if (!built || state == null || !state.Enabled || state.CodeExpiresAt == null || expiryText == null) return;
            if (!force && Time.realtimeSinceStartup - lastCountdownAt < 1f) return;
            lastCountdownAt = Time.realtimeSinceStartup;
            System.DateTime exp;
            string t;
            if (System.DateTime.TryParse(state.CodeExpiresAt, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out exp))
            {
                double left = (exp - System.DateTime.UtcNow).TotalSeconds;
                t = left > 0 ? "Valid for " + ((int)left / 60) + ":" + ((int)left % 60).ToString("00", CultureInfo.InvariantCulture) + ", one use" : "Expired. Press New code.";
            }
            else t = "";
            if (t != lastCountdown) { lastCountdown = t; expiryText.text = t; }
        }

        private static string LastSeenText(string iso)
        {
            System.DateTime d;
            if (string.IsNullOrEmpty(iso) || !System.DateTime.TryParse(iso, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out d)) return "not seen yet";
            double m = (System.DateTime.UtcNow - d).TotalMinutes;
            if (m < 1) return "seen just now";
            if (m < 60) return "seen " + (int)m + " min ago";
            if (m < 1440) return "seen " + (int)(m / 60) + " h ago";
            return "seen " + (int)(m / 1440) + " days ago";
        }

        private static void SetQr(string text)
        {
            if (text == qrShown) return;
            qrShown = text;
            if (string.IsNullOrEmpty(text)) { qrImage.enabled = false; return; }
            int version;
            bool[,] m = Qr.Encode(text, out version);
            if (m == null) { qrImage.enabled = false; Log.Warn("connect window: the pairing text is too long for the QR encoder (" + text.Length + " chars)"); return; }
            int n = m.GetLength(0), q = 4, size = n + 2 * q;           // quiet zone of 4 modules
            Color32[] px = new Color32[size * size];
            Color32 white = new Color32(255, 255, 255, 255), black = new Color32(0, 0, 0, 255);
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    int mx = x - q, my = n - 1 - (y - q);                // texture row 0 is the bottom
                    px[y * size + x] = mx >= 0 && my >= 0 && mx < n && my < n && m[n - 1 - my, mx] ? black : white;
                }
            if (qrTex == null || qrTex.width != size)
            {
                if (qrTex != null) UnityEngine.Object.Destroy(qrTex);
                qrTex = new Texture2D(size, size, TextureFormat.RGBA32, false) { filterMode = FilterMode.Point, wrapMode = TextureWrapMode.Clamp };
            }
            qrTex.SetPixels32(px); qrTex.Apply(false);
            qrImage.texture = qrTex; qrImage.enabled = true;
        }

        // ---------------------------------------------------------------- building the window (timed steps)

        private static Transform content;

        private static void BuildSteps()
        {
            Transform panelT = null;
            steps.Enqueue(delegate ()
            {
                RectTransform dim = NewRect("dim", root.transform);
                Stretch(dim);
                Image di = dim.gameObject.AddComponent<Image>(); di.color = new Color(0f, 0f, 0f, 0.63f); di.raycastTarget = true;
                RectTransform panel = NewRect("panel", root.transform);
                panel.anchorMin = panel.anchorMax = new Vector2(0.5f, 0.5f); panel.pivot = new Vector2(0.5f, 0.5f);
                panel.sizeDelta = new Vector2(PanelWidth, 0f);
                Image pi = panel.gameObject.AddComponent<Image>(); pi.color = panelColor; pi.raycastTarget = true;
                VerticalLayoutGroup v = panel.gameObject.AddComponent<VerticalLayoutGroup>();
                v.padding = new RectOffset(24, 24, 18, 20); v.spacing = 10; v.childControlWidth = true; v.childControlHeight = true;
                v.childForceExpandWidth = true; v.childForceExpandHeight = false;
                ContentSizeFitter f = panel.gameObject.AddComponent<ContentSizeFitter>(); f.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
                panelT = panel; content = panel;
                // header row: title + Close
                Transform hr = Row(content, 56f, headerColor);
                LocText t = NewText(hr, "Connect a phone", 34, TMPro.TextAlignmentOptions.Left); Flex(t.gameObject, 1f, -1f);
                closeButton = NewButton(hr, "Close", 140f, 44f, delegate () { PauseScreen p = PauseScreen.Instance; Close(); });
            });
            steps.Enqueue(delegate ()
            {
                nameText = NewText(content, "", 36, TMPro.TextAlignmentOptions.Left);
                Transform sr = Row(content, 52f, default(Color));
                switchLabel = NewText(sr, "Let phones connect to this game", 26, TMPro.TextAlignmentOptions.Left); Flex(switchLabel.gameObject, 1f, -1f);
                switchButton = NewButton(sr, "Off", 140f, 48f, delegate () { Send("set_enabled", !(state != null && state.Enabled)); });
                switchBtnText = switchButton.GetComponentInChildren<LocText>(true);
                offNote = NewText(content, "", 22, TMPro.TextAlignmentOptions.Left);
            });
            steps.Enqueue(delegate ()
            {
                GameObject sec = new GameObject("on", typeof(RectTransform));
                sec.transform.SetParent(content, false);
                HorizontalLayoutGroup h = sec.AddComponent<HorizontalLayoutGroup>();
                h.spacing = 20; h.childControlWidth = true; h.childControlHeight = true; h.childForceExpandWidth = false; h.childForceExpandHeight = false;
                onSection = sec;
                GameObject q = new GameObject("qr", typeof(RectTransform));
                q.transform.SetParent(sec.transform, false);
                qrImage = q.AddComponent<RawImage>(); qrImage.color = Color.white; qrImage.enabled = false;
                LayoutElement le = q.AddComponent<LayoutElement>(); le.preferredWidth = 330f; le.preferredHeight = 330f; le.minWidth = 330f; le.minHeight = 330f;
                GameObject col = new GameObject("col", typeof(RectTransform));
                col.transform.SetParent(sec.transform, false);
                VerticalLayoutGroup v = col.AddComponent<VerticalLayoutGroup>();
                v.spacing = 6; v.childControlWidth = true; v.childControlHeight = true; v.childForceExpandWidth = true; v.childForceExpandHeight = false;
                Flex(col, 1f, -1f);
                NewText(col.transform, "Code", 22, TMPro.TextAlignmentOptions.Left);
                codeText = NewText(col.transform, "", 64, TMPro.TextAlignmentOptions.Left);
                expiryText = NewText(col.transform, "", 22, TMPro.TextAlignmentOptions.Left);
                newCodeButton = NewButton(col.transform, "New code", 200f, 44f, delegate () { Send("new_code"); });
                addrText = NewText(col.transform, "", 22, TMPro.TextAlignmentOptions.Left);
            });
            steps.Enqueue(delegate () { devHeader = NewText(content, "", 26, TMPro.TextAlignmentOptions.Left); });
            for (int i = 0; i < DeviceRows; i++)
            {
                steps.Enqueue(delegate ()
                {
                    DevRow r = new DevRow();
                    Transform hr = Row(content, 44f, default(Color));
                    r.Go = hr.gameObject;
                    r.Text = NewText(hr, "", 22, TMPro.TextAlignmentOptions.Left); Flex(r.Text.gameObject, 1f, -1f);
                    DevRow rr = r;
                    r.Remove = NewButton(hr, "Remove", 140f, 40f, delegate () { if (rr.DeviceId != null) Send("remove_device", null, rr.DeviceId); });
                    r.Go.SetActive(false);
                    rows.Add(r);
                });
            }
            steps.Enqueue(delegate ()
            {
                Transform pr = Row(content, 48f, default(Color));
                LocText l = NewText(pr, "iPhone in Safari (plain http)", 24, TMPro.TextAlignmentOptions.Left); Flex(l.gameObject, 1f, -1f);
                plainButton = NewButton(pr, "Off", 140f, 44f, delegate () { Send("set_plain_http", !(state != null && state.PlainHttp)); });
                plainBtnText = plainButton.GetComponentInChildren<LocText>(true);
                plainNote = NewText(content, "", 20, TMPro.TextAlignmentOptions.Left);
            });
            steps.Enqueue(delegate ()
            {
                Transform rr = Row(content, 48f, default(Color));
                resetButton = NewButton(rr, "Reset identity", 240f, 44f, AskReset);
                statusText = NewText(rr, "", 22, TMPro.TextAlignmentOptions.Left); Flex(statusText.gameObject, 1f, -1f);
            });
        }

        // ---------------------------------------------------------------- small UI helpers

        private static RectTransform NewRect(string name, Transform parent)
        {
            GameObject g = new GameObject(name, typeof(RectTransform));
            g.transform.SetParent(parent, false);
            return (RectTransform)g.transform;
        }

        private static void Stretch(RectTransform r) { r.anchorMin = Vector2.zero; r.anchorMax = Vector2.one; r.offsetMin = Vector2.zero; r.offsetMax = Vector2.zero; }

        private static void Flex(GameObject g, float w, float h)
        {
            LayoutElement le = g.GetComponent<LayoutElement>() ?? g.AddComponent<LayoutElement>();
            if (w >= 0) le.flexibleWidth = w;
            if (h >= 0) le.flexibleHeight = h;
        }

        private static Transform Row(Transform parent, float height, Color bg)
        {
            RectTransform r = NewRect("row", parent);
            if (bg.a > 0f) { Image im = r.gameObject.AddComponent<Image>(); im.color = bg; }
            HorizontalLayoutGroup h = r.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.spacing = 14; h.padding = new RectOffset(bg.a > 0f ? 12 : 0, bg.a > 0f ? 12 : 0, 0, 0);
            h.childControlWidth = true; h.childControlHeight = true; h.childForceExpandWidth = false; h.childForceExpandHeight = true; h.childAlignment = TextAnchor.MiddleLeft;
            LayoutElement le = r.gameObject.AddComponent<LayoutElement>(); le.minHeight = height; le.preferredHeight = height;
            return r;
        }

        private static LocText NewText(Transform parent, string text, int size, TMPro.TextAlignmentOptions align)
        {
            GameObject g = UnityEngine.Object.Instantiate(textTemplate.gameObject);
            g.name = "text";
            g.transform.SetParent(parent, false);
            g.SetActive(true);
            LocText t = g.GetComponent<LocText>();
            t.allowOverride = true;
            t.text = text; t.fontSize = size; t.alignment = align; t.enableWordWrapping = true; t.raycastTarget = false;
            foreach (LayoutElement old in g.GetComponents<LayoutElement>()) UnityEngine.Object.Destroy(old);
            ContentSizeFitter cf = g.GetComponent<ContentSizeFitter>(); if (cf != null) UnityEngine.Object.Destroy(cf);
            return t;
        }

        private static KButton NewButton(Transform parent, string text, float w, float h, System.Action click)
        {
            GameObject g = UnityEngine.Object.Instantiate(buttonPrefab);
            g.name = text + "Button";
            g.transform.SetParent(parent, false);
            g.SetActive(true);
            foreach (LocText t in g.GetComponentsInChildren<LocText>(true)) t.text = t.name == "Hotkey" ? "" : text;
            LayoutElement le = g.GetComponent<LayoutElement>() ?? g.AddComponent<LayoutElement>();
            le.minWidth = w; le.preferredWidth = w; le.minHeight = h; le.preferredHeight = h; le.flexibleWidth = 0;
            KButton b = g.GetComponent<KButton>();
            b.onClick += click;
            return b;
        }

        private static void ReadColors(PauseScreen screen)
        {
            try
            {
                Dictionary<string, ColorStyleSetting> map = new Dictionary<string, ColorStyleSetting>();
                Collect(screen.gameObject, map);
                if (DetailsScreen.Instance != null) Collect(DetailsScreen.Instance.gameObject, map);
                ColorStyleSetting c;
                if (map.TryGetValue("colorstyle_darkBG", out c) && c != null) panelColor = c.activeColor;
                if (map.TryGetValue("colorstyle_title", out c) && c != null) headerColor = c.activeColor;
            }
            catch (Exception e) { Log.Warn("connect window: colors fall back (" + e.Message + ")"); }
        }

        private static void Collect(GameObject go, Dictionary<string, ColorStyleSetting> map)
        {
            foreach (KImage k in go.GetComponentsInChildren<KImage>(true))
                if (k != null && k.colorStyleSetting != null && !map.ContainsKey(k.colorStyleSetting.name)) map[k.colorStyleSetting.name] = k.colorStyleSetting;
        }
    }
}
