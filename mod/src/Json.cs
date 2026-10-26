using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace OniCompanionLink
{
    /// <summary>Minimal JSON writer (no dependencies). Commas are automatic.</summary>
    internal sealed class Json
    {
        private readonly StringBuilder sb;
        private readonly Stack<bool> first = new Stack<bool>();
        private bool afterKey;

        public Json(int capacity = 4096) { sb = new StringBuilder(capacity); }

        public override string ToString() { return sb.ToString(); }
        public int Length { get { return sb.Length; } }

        private void Sep()
        {
            if (afterKey) { afterKey = false; return; }
            if (first.Count > 0)
            {
                if (first.Peek()) { first.Pop(); first.Push(false); }
                else sb.Append(',');
            }
        }

        public Json Obj() { Sep(); sb.Append('{'); first.Push(true); return this; }
        public Json EndObj() { first.Pop(); sb.Append('}'); return this; }
        public Json Arr() { Sep(); sb.Append('['); first.Push(true); return this; }
        public Json EndArr() { first.Pop(); sb.Append(']'); return this; }

        public Json Key(string name)
        {
            Sep();
            WriteString(name);
            sb.Append(':');
            afterKey = true;
            return this;
        }

        public Json Str(string s)
        {
            Sep();
            if (s == null) sb.Append("null"); else WriteString(s);
            return this;
        }

        public Json Null() { Sep(); sb.Append("null"); return this; }
        public Json Bool(bool b) { Sep(); sb.Append(b ? "true" : "false"); return this; }
        public Json Int(long v) { Sep(); sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }

        public Json Num(double v)
        {
            Sep();
            if (double.IsNaN(v) || double.IsInfinity(v)) { sb.Append('0'); return this; }
            // Round to 6 significant-ish decimals to keep files small and stable.
            double r = Math.Round(v, 6);
            if (r == Math.Floor(r) && Math.Abs(r) < 1e15) sb.Append(((long)r).ToString(CultureInfo.InvariantCulture));
            else sb.Append(r.ToString("R", CultureInfo.InvariantCulture));
            return this;
        }

        // Convenience: key + value
        public Json P(string k, string v) { return Key(k).Str(v); }
        public Json P(string k, double v) { return Key(k).Num(v); }
        public Json PI(string k, long v) { return Key(k).Int(v); }
        public Json P(string k, bool v) { return Key(k).Bool(v); }

        public Json StrArr(IEnumerable<string> items)
        {
            Arr();
            if (items != null) foreach (string s in items) Str(s);
            return EndArr();
        }

        public Json Raw0(string rawJsonValue)
        {
            Sep();
            sb.Append(rawJsonValue);
            return this;
        }

        public Json Raw(string rawJsonMembers)
        {
            // Inserts already-serialized members ("\"a\":1,\"b\":2") into the current object.
            if (string.IsNullOrEmpty(rawJsonMembers)) return this;
            Sep();
            sb.Append(rawJsonMembers);
            return this;
        }

        private void WriteString(string s)
        {
            sb.Append('"');
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
