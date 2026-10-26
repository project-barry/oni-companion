using System;
using System.Text;

namespace OniCompanionLink
{
    /// <summary>
    /// Our own QR encoder for the Connect a phone window: byte mode (UTF-8), error correction level M, versions 1 to 15
    /// (15 holds 412 bytes, the contract's 400-byte QR text limit), automatic mask choice by the standard's four penalty rules.
    /// No Unity types: tested offline against known vectors (mod/tests/QrTest). Encode returns null when the text does not fit.
    /// </summary>
    internal static class Qr
    {
        public const int MaxVersion = 15;

        // Level M, per version 1..15: EC codewords per block, blocks in group 1, data codewords per group-1 block, blocks in group 2, data codewords per group-2 block.
        private static readonly int[,] Blocks =
        {
            { 10, 1, 16, 0, 0 }, { 16, 1, 28, 0, 0 }, { 26, 1, 44, 0, 0 }, { 18, 2, 32, 0, 0 }, { 24, 2, 43, 0, 0 },
            { 16, 4, 27, 0, 0 }, { 18, 4, 31, 0, 0 }, { 22, 2, 38, 2, 39 }, { 22, 3, 36, 2, 37 }, { 26, 4, 43, 1, 44 },
            { 30, 1, 50, 4, 51 }, { 22, 6, 36, 2, 37 }, { 22, 8, 37, 1, 38 }, { 24, 4, 40, 5, 41 }, { 24, 5, 41, 5, 42 }
        };

        private static readonly int[][] Align =
        {
            new int[0], new[] { 6, 18 }, new[] { 6, 22 }, new[] { 6, 26 }, new[] { 6, 30 }, new[] { 6, 34 },
            new[] { 6, 22, 38 }, new[] { 6, 24, 42 }, new[] { 6, 26, 46 }, new[] { 6, 28, 50 }, new[] { 6, 30, 54 },
            new[] { 6, 32, 58 }, new[] { 6, 34, 62 }, new[] { 6, 26, 46, 66 }, new[] { 6, 26, 48, 70 }
        };

        private static int DataCodewords(int v)
        {
            return Blocks[v - 1, 1] * Blocks[v - 1, 2] + Blocks[v - 1, 3] * Blocks[v - 1, 4];
        }

        /// <summary>Largest byte count that fits version v in byte mode, level M.</summary>
        public static int Capacity(int v)
        {
            int bits = DataCodewords(v) * 8 - 4 - (v <= 9 ? 8 : 16);
            return bits / 8;
        }

        /// <summary>Modules (true = dark) of the smallest version that holds the text, or null if it does not fit versions 1..15. size = 17 + 4 * version.</summary>
        public static bool[,] Encode(string text, out int version, int forceMask = -1)
        {
            version = 0;
            byte[] data = new UTF8Encoding(false).GetBytes(text ?? "");
            for (int v = 1; v <= MaxVersion; v++)
            {
                if (data.Length <= Capacity(v)) { version = v; return Build(data, v, forceMask); }
            }
            return null;
        }

        public static bool[,] Encode(string text) { int v; return Encode(text, out v); }

        // ---- data + error correction ----

        private sealed class Bits
        {
            public readonly System.Collections.Generic.List<byte> Bytes = new System.Collections.Generic.List<byte>();
            public int Count;
            public void Add(int value, int n)
            {
                for (int i = n - 1; i >= 0; i--)
                {
                    if ((Count & 7) == 0) Bytes.Add(0);
                    if (((value >> i) & 1) != 0) Bytes[Bytes.Count - 1] |= (byte)(0x80 >> (Count & 7));
                    Count++;
                }
            }
        }

        private static bool[,] Build(byte[] data, int v, int forceMask)
        {
            int total = DataCodewords(v);
            Bits b = new Bits();
            b.Add(4, 4);                              // byte mode
            b.Add(data.Length, v <= 9 ? 8 : 16);
            for (int i = 0; i < data.Length; i++) b.Add(data[i], 8);
            int cap = total * 8;
            b.Add(0, Math.Min(4, cap - b.Count));     // terminator
            if ((b.Count & 7) != 0) b.Add(0, 8 - (b.Count & 7));
            int pad = 0;
            while (b.Bytes.Count < total) { b.Bytes.Add((byte)(pad == 0 ? 0xEC : 0x11)); pad ^= 1; }

            // split into blocks, add Reed-Solomon, interleave
            int ecLen = Blocks[v - 1, 0];
            int n1 = Blocks[v - 1, 1], d1 = Blocks[v - 1, 2], n2 = Blocks[v - 1, 3], d2 = Blocks[v - 1, 4];
            int nb = n1 + n2;
            byte[][] dat = new byte[nb][];
            byte[][] ecc = new byte[nb][];
            byte[] gen = Generator(ecLen);
            int pos = 0;
            for (int k = 0; k < nb; k++)
            {
                int len = k < n1 ? d1 : d2;
                dat[k] = new byte[len];
                b.Bytes.CopyTo(pos, dat[k], 0, len);
                pos += len;
                ecc[k] = Remainder(dat[k], gen);
            }
            byte[] all = new byte[total + nb * ecLen];
            int o = 0;
            int maxd = Math.Max(d1, d2);
            for (int i = 0; i < maxd; i++)
                for (int k = 0; k < nb; k++)
                    if (i < dat[k].Length) all[o++] = dat[k][i];
            for (int i = 0; i < ecLen; i++)
                for (int k = 0; k < nb; k++) all[o++] = ecc[k][i];

            return Place(all, v, forceMask);
        }

        private static readonly byte[] Exp = new byte[512];
        private static readonly int[] Log = new int[256];
        static Qr()
        {
            int x = 1;
            for (int i = 0; i < 255; i++)
            {
                Exp[i] = (byte)x; Log[x] = i;
                x <<= 1; if (x >= 256) x ^= 0x11D;
            }
            for (int i = 255; i < 512; i++) Exp[i] = Exp[i - 255];
        }

        private static int Mul(int a, int b) { return (a == 0 || b == 0) ? 0 : Exp[Log[a] + Log[b]]; }

        private static byte[] Generator(int degree)
        {
            byte[] g = new byte[degree];   // coefficients below the leading 1, highest power first
            g[degree - 1] = 1;
            int root = 1;
            for (int i = 0; i < degree; i++)
            {
                for (int j = 0; j < degree; j++)
                {
                    g[j] = (byte)Mul(g[j], root);
                    if (j + 1 < degree) g[j] ^= g[j + 1];
                }
                root = Mul(root, 2);
            }
            return g;
        }

        private static byte[] Remainder(byte[] data, byte[] gen)
        {
            byte[] r = new byte[gen.Length];
            foreach (byte d in data)
            {
                int f = d ^ r[0];
                Array.Copy(r, 1, r, 0, r.Length - 1);
                r[r.Length - 1] = 0;
                for (int i = 0; i < r.Length; i++) r[i] ^= (byte)Mul(gen[i], f);
            }
            return r;
        }

        // ---- matrix ----

        private static bool[,] Place(byte[] codewords, int v, int forceMask)
        {
            int n = 17 + 4 * v;
            bool[,] best = null;
            int bestPenalty = int.MaxValue;
            bool[,] func = new bool[n, n];
            bool[,] baseM = new bool[n, n];
            DrawFunction(baseM, func, v);
            // data bits in zigzag order
            bool[,] withData = (bool[,])baseM.Clone();
            int bitIdx = 0, totalBits = codewords.Length * 8;
            for (int right = n - 1; right >= 1; right -= 2)
            {
                if (right == 6) right = 5;
                for (int vert = 0; vert < n; vert++)
                {
                    for (int j = 0; j < 2; j++)
                    {
                        int x = right - j;
                        bool upward = ((right + 1) & 2) == 0;
                        int y = upward ? n - 1 - vert : vert;
                        if (func[y, x]) continue;
                        if (bitIdx < totalBits)
                        {
                            withData[y, x] = ((codewords[bitIdx >> 3] >> (7 - (bitIdx & 7))) & 1) != 0;
                            bitIdx++;
                        }
                    }
                }
            }
            for (int mask = 0; mask < 8; mask++)
            {
                if (forceMask >= 0 && mask != forceMask) continue;
                bool[,] m = (bool[,])withData.Clone();
                for (int y = 0; y < n; y++)
                    for (int x = 0; x < n; x++)
                        if (!func[y, x] && MaskBit(mask, x, y)) m[y, x] = !m[y, x];
                DrawFormat(m, mask);
                int p = Penalty(m, n);
                if (p < bestPenalty) { bestPenalty = p; best = m; }
            }
            return best;
        }

        private static bool MaskBit(int mask, int x, int y)
        {
            switch (mask)
            {
                case 0: return (x + y) % 2 == 0;
                case 1: return y % 2 == 0;
                case 2: return x % 3 == 0;
                case 3: return (x + y) % 3 == 0;
                case 4: return (x / 3 + y / 2) % 2 == 0;
                case 5: return x * y % 2 + x * y % 3 == 0;
                case 6: return (x * y % 2 + x * y % 3) % 2 == 0;
                default: return ((x + y) % 2 + x * y % 3) % 2 == 0;
            }
        }

        private static void Set(bool[,] m, bool[,] func, int x, int y, bool dark)
        {
            int n = m.GetLength(0);
            if (x < 0 || y < 0 || x >= n || y >= n) return;
            m[y, x] = dark; func[y, x] = true;
        }

        private static void DrawFunction(bool[,] m, bool[,] func, int v)
        {
            int n = m.GetLength(0);
            for (int i = 0; i < n; i++)                         // timing patterns
            {
                Set(m, func, 6, i, i % 2 == 0);
                Set(m, func, i, 6, i % 2 == 0);
            }
            Finder(m, func, 3, 3); Finder(m, func, n - 4, 3); Finder(m, func, 3, n - 4);
            int[] al = Align[v - 1];
            for (int a = 0; a < al.Length; a++)
                for (int c = 0; c < al.Length; c++)
                {
                    if ((a == 0 && c == 0) || (a == 0 && c == al.Length - 1) || (a == al.Length - 1 && c == 0)) continue;
                    for (int dy = -2; dy <= 2; dy++)
                        for (int dx = -2; dx <= 2; dx++)
                            Set(m, func, al[a] + dx, al[c] + dy, Math.Max(Math.Abs(dx), Math.Abs(dy)) != 1);
                }
            DrawFormat(m, 0);                                    // reserves the format areas (real bits drawn per mask)
            if (v >= 7)
            {
                int rem = v;
                for (int i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >> 11) * 0x1F25);
                int bits = (v << 12) | rem;
                for (int i = 0; i < 18; i++)
                {
                    bool bit = ((bits >> i) & 1) != 0;
                    int a = n - 11 + i % 3, bb = i / 3;
                    Set(m, func, a, bb, bit);
                    Set(m, func, bb, a, bit);
                }
            }
            Set(m, func, 8, n - 8, true);                        // the always-dark module
            // mark format areas as function (DrawFormat already set them through Set via the local func? no: do it here)
            for (int i = 0; i < 9; i++) { func[8, i] = true; func[i, 8] = true; }
            for (int i = 0; i < 8; i++) { func[8, n - 1 - i] = true; func[n - 1 - i, 8] = true; }
        }

        private static void Finder(bool[,] m, bool[,] func, int cx, int cy)
        {
            for (int dy = -4; dy <= 4; dy++)
                for (int dx = -4; dx <= 4; dx++)
                {
                    int d = Math.Max(Math.Abs(dx), Math.Abs(dy));
                    Set(m, func, cx + dx, cy + dy, d != 2 && d != 4);
                }
        }

        private static void DrawFormat(bool[,] m, int mask)
        {
            int n = m.GetLength(0);
            int data = (0 << 3) | mask;                          // level M = 00
            int rem = data;
            for (int i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537);
            int bits = ((data << 10) | rem) ^ 0x5412;
            for (int i = 0; i <= 5; i++) m[i, 8] = Bit(bits, i);
            m[7, 8] = Bit(bits, 6);
            m[8, 8] = Bit(bits, 7);
            m[8, 7] = Bit(bits, 8);
            for (int i = 9; i < 15; i++) m[8, 14 - i] = Bit(bits, i);
            for (int i = 0; i < 8; i++) m[8, n - 1 - i] = Bit(bits, i);
            for (int i = 8; i < 15; i++) m[n - 15 + i, 8] = Bit(bits, i);
            m[n - 8, 8] = true;
        }

        private static bool Bit(int x, int i) { return ((x >> i) & 1) != 0; }

        // ---- mask penalty (the standard's four rules) ----

        private static int Penalty(bool[,] m, int n)
        {
            int result = 0;
            for (int pass = 0; pass < 2; pass++)
            {
                for (int a = 0; a < n; a++)
                {
                    int run = 1;
                    for (int b = 1; b < n; b++)
                    {
                        bool prev = pass == 0 ? m[a, b - 1] : m[b - 1, a];
                        bool cell = pass == 0 ? m[a, b] : m[b, a];
                        if (cell == prev) { run++; if (run == 5) result += 3; else if (run > 5) result++; }
                        else run = 1;
                    }
                    // rule 3: 1:1:3:1:1 dark-light-dark with four light modules on one side
                    for (int b = -4; b + 7 <= n; b++)
                    {
                        if (Pattern(m, a, b, pass, true)) result += 40;
                        if (Pattern(m, a, b, pass, false)) result += 40;
                    }
                }
            }
            for (int y = 0; y < n - 1; y++)
                for (int x = 0; x < n - 1; x++)
                {
                    bool c = m[y, x];
                    if (c == m[y, x + 1] && c == m[y + 1, x] && c == m[y + 1, x + 1]) result += 3;
                }
            int dark = 0;
            for (int y = 0; y < n; y++) for (int x = 0; x < n; x++) if (m[y, x]) dark++;
            int tot = n * n;
            int k = Math.Abs(dark * 20 - tot * 10) / tot;   // whole 5% steps away from 50% dark
            result += k * 10;
            return result;
        }

        private static readonly bool[] PatA = { true, false, true, true, true, false, true, false, false, false, false };
        private static readonly bool[] PatB = { false, false, false, false, true, false, true, true, true, false, true };

        private static bool Pattern(bool[,] m, int a, int start, int pass, bool first)
        {
            bool[] pat = first ? PatA : PatB;
            int n = m.GetLength(0);
            for (int i = 0; i < 11; i++)
            {
                int k = start + i;
                bool cell = k < 0 || k >= n ? false : (pass == 0 ? m[a, k] : m[k, a]);   // outside the symbol counts as light
                if (cell != pat[i]) return false;
            }
            return true;
        }
    }
}
