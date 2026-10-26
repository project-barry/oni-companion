using System;
using System.IO;
using System.Text;

// Writes, for every input line in <cases.txt> (one text per line, escaped \n not used), the matrix as lines of 0/1:
//   "#<index> v<version>" then the rows. check.py compares against segno and decodes with OpenCV.
internal static class Program
{
    private static int Main(string[] args)
    {
        string[] lines = File.ReadAllLines(args[0], Encoding.UTF8);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < lines.Length; i++)
        {
            int v;
            int fm = args.Length > 2 ? int.Parse(args[2]) : -1;
            bool[,] m = OniCompanionLink.Qr.Encode(lines[i], out v, fm);
            if (m == null) { sb.Append("#" + i + " none\n"); continue; }
            sb.Append("#" + i + " v" + v + "\n");
            int n = m.GetLength(0);
            for (int y = 0; y < n; y++)
            {
                for (int x = 0; x < n; x++) sb.Append(m[y, x] ? '1' : '0');
                sb.Append('\n');
            }
        }
        File.WriteAllText(args[1], sb.ToString());
        return 0;
    }
}
