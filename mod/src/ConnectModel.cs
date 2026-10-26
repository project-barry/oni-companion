using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace OniCompanionLink
{
    // Connect a phone (v1.4): the files between the service and the mod (contracts/pairing.schema.json). No Unity types in this file,
    // so mod/tests/ConnectTest runs it offline. The mod holds no secret: state.json has no token and no private key.

    internal sealed class PairedDeviceInfo
    {
        public string DeviceId, Label, Platform, PairedAt, LastSeen, Transport;
    }

    internal sealed class PairState
    {
        public bool Enabled, Listening, PlainHttp;
        public int Port, PlainHttpPort;                 // 0 = null
        public string InstanceId, Name, FingerprintTag, Fingerprint, CoreVersion;
        public List<string> Addresses = new List<string>();     // "192.168.1.23 (Wi-Fi)" style lines are made by the window; these are raw
        public List<string> AddressKinds = new List<string>();
        public string CodeDisplay, CodeExpiresAt, QrText, PlainHttpNote;
        public int CodeFailuresLeft;
        public List<PairedDeviceInfo> Devices = new List<PairedDeviceInfo>();
        public long LastSeq; public string LastState, LastMessage;   // lastRequest, LastSeq 0 = null
        public int Pid;
        public string UpdatedAt;

        /// <summary>Parse state.json text. Returns null when it is not a schema 1 state file (the window then shows "not running").</summary>
        public static PairState Parse(string text)
        {
            try
            {
                JObject o;
                using (JsonTextReader r = new JsonTextReader(new StringReader(text)) { DateParseHandling = DateParseHandling.None })
                    o = JObject.Load(r);
                if (Int((JToken)o["schema"]) != 1) return null;
                PairState s = new PairState();
                s.Enabled = Bool(o["enabled"]); s.Listening = Bool(o["listening"]); s.PlainHttp = Bool(o["plainHttp"]);
                s.Port = Int(o["port"]); s.PlainHttpPort = Int(o["plainHttpPort"]);
                s.Pid = Int(o["pid"]); s.UpdatedAt = Str(o["updatedAt"]);
                JObject id = o["identity"] as JObject;
                if (id == null) return null;
                s.InstanceId = Str(id["instanceId"]); s.Name = Str(id["name"]); s.Fingerprint = Str(id["fingerprint"]);
                s.FingerprintTag = Str(id["fingerprintTag"]); s.CoreVersion = Str(id["coreVersion"]);
                JArray ad = o["addresses"] as JArray;
                if (ad != null) foreach (JToken t in ad) { s.Addresses.Add(Str(t["address"])); s.AddressKinds.Add(Str(t["kind"])); }
                JObject code = o["code"] as JObject;
                if (code != null) { s.CodeDisplay = Str(code["display"]); s.CodeExpiresAt = Str(code["expiresAt"]); s.CodeFailuresLeft = Int(code["failuresLeft"]); }
                s.QrText = Str(o["qrText"]); s.PlainHttpNote = Str(o["plainHttpNote"]);
                JArray dv = o["devices"] as JArray;
                if (dv != null)
                    foreach (JToken t in dv)
                        s.Devices.Add(new PairedDeviceInfo { DeviceId = Str(t["deviceId"]), Label = Str(t["label"]), Platform = Str(t["platform"]),
                            PairedAt = Str(t["pairedAt"]), LastSeen = Str(t["lastSeen"]), Transport = Str(t["transport"]) });
                JObject lr = o["lastRequest"] as JObject;
                if (lr != null) { s.LastSeq = Long(lr["seq"]); s.LastState = Str(lr["state"]); s.LastMessage = Str(lr["message"]); }
                return s;
            }
            catch { return null; }
        }

        private static string Str(JToken t) { return t == null || t.Type == JTokenType.Null ? null : t.ToString(); }
        private static bool Bool(JToken t) { return t != null && t.Type == JTokenType.Boolean && (bool)t; }
        private static int Int(JToken t) { return (int)Long(t); }
        private static long Long(JToken t) { return t != null && t.Type == JTokenType.Integer ? (long)t : 0; }
    }

    /// <summary>The pairing folder: state.json (read) and requests/req-&lt;seq&gt;.json (written, temp file then rename).</summary>
    internal sealed class PairingFiles
    {
        public const int RequestMaxAgeSeconds = 10;
        public readonly string Dir, StatePath, RequestsDir;

        public PairingFiles(string companionDir)
        {
            Dir = Path.Combine(companionDir, "pairing");
            StatePath = Path.Combine(Dir, "state.json");
            RequestsDir = Path.Combine(Dir, "requests");
        }

        public PairState ReadState()
        {
            try { return File.Exists(StatePath) ? PairState.Parse(File.ReadAllText(StatePath, Encoding.UTF8)) : null; }
            catch { return null; }     // being replaced right now: the watcher fires again when the rename lands
        }

        /// <summary>seq = (lastRequest.seq from state.json, or the highest req file, whichever is larger) + 1.</summary>
        public long NextSeq(PairState state)
        {
            long max = state != null ? state.LastSeq : 0;
            try
            {
                if (Directory.Exists(RequestsDir))
                    foreach (string f in Directory.GetFiles(RequestsDir, "req-*.json"))
                    {
                        string n = Path.GetFileNameWithoutExtension(f).Substring(4);
                        long v;
                        if (long.TryParse(n, NumberStyles.None, CultureInfo.InvariantCulture, out v) && v > max) max = v;
                    }
            }
            catch { }
            return max + 1;
        }

        /// <summary>The request JSON for one allow-listed type (set_enabled, new_code, remove_device, reset_identity, set_plain_http).</summary>
        public static string BuildRequest(long seq, string createdAt, string type, bool? enabled, string deviceId, bool? confirm)
        {
            Json j = new Json(256);
            j.Obj().PI("schema", 1).PI("seq", (int)seq).P("createdAt", createdAt).P("type", type);
            if (type == "set_enabled" || type == "set_plain_http") j.P("enabled", enabled == true);
            if (type == "remove_device") j.P("deviceId", deviceId);
            if (type == "reset_identity") j.P("confirm", confirm == true);
            j.EndObj();
            return j.ToString();
        }

        /// <summary>Write one request atomically: req-&lt;seq&gt;.json.tmp, then rename (the tmp name never matches req-*.json). Returns the seq.</summary>
        public long WriteRequest(PairState state, string type, bool? enabled = null, string deviceId = null, bool? confirm = null)
        {
            long seq = NextSeq(state);
            string path = Path.Combine(RequestsDir, "req-" + seq.ToString(CultureInfo.InvariantCulture) + ".json");
            Files.WriteAtomic(path, BuildRequest(seq, System.DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture), type, enabled, deviceId, confirm));
            return seq;
        }
    }
}
