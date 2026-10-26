using System;
using System.IO;
using System.IO.Compression;

// Usage: dotnet run -- <outdir>. Writes test PNGs; tests/PngTest/check.py decodes them with the stdlib and compares pixels.
// PngCodec below is copied between the BEGIN PNG / END PNG markers of mod/src/Art.cs by run.sh (so the test runs the shipped code).
public static class Program
{
    public static int Main(string[] a)
    {
        string dir = a.Length > 0 ? a[0] : ".";
        Directory.CreateDirectory(dir);
        int w = 37, h = 23;   // odd sizes on purpose
        byte[] px = new byte[w * h * 4];
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                int i = (y * w + x) * 4;
                px[i] = (byte)(x * 7); px[i + 1] = (byte)(y * 11); px[i + 2] = (byte)((x ^ y) * 5); px[i + 3] = (byte)((x + y) % 5 == 0 ? 0 : 255 - x * 3);
            }
        File.WriteAllBytes(Path.Combine(dir, "t1.png"), PngCodec.Encode(w, h, px));
        File.WriteAllBytes(Path.Combine(dir, "t1.rgba"), px);
        byte[] big = new byte[256 * 256 * 4];
        var rnd = new Random(1);
        rnd.NextBytes(big);
        File.WriteAllBytes(Path.Combine(dir, "t2.png"), PngCodec.Encode(256, 256, big));
        File.WriteAllBytes(Path.Combine(dir, "t2.rgba"), big);
        byte[] flipped = PngCodec.FlipRows(px, w, h);
        File.WriteAllBytes(Path.Combine(dir, "t3.png"), PngCodec.Encode(w, h, flipped));
        File.WriteAllBytes(Path.Combine(dir, "t3.rgba"), flipped);
        byte[] small = PngCodec.Downscale(big, 256, 256, 100, 100);
        File.WriteAllBytes(Path.Combine(dir, "t4.png"), PngCodec.Encode(100, 100, small));
        File.WriteAllBytes(Path.Combine(dir, "t4.rgba"), small);
        Console.WriteLine("ok");
        return 0;
    }
}

internal static class PngCodec
{
//PNG_HERE
    public static byte[] FlipRows(byte[] src, int w, int h)
    {
        int stride = w * 4;
        byte[] dst = new byte[src.Length];
        for (int y = 0; y < h; y++) Buffer.BlockCopy(src, y * stride, dst, (h - 1 - y) * stride, stride);
        return dst;
    }
//DOWNSCALE_HERE
}
