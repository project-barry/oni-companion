using System.IO;
using System.Text;

namespace OniCompanionLink
{
    internal static class Files
    {
        /// <summary>Write to name.tmp, then rename over name. Never leaves a half-written target.</summary>
        public static void WriteAtomic(string path, string content)
        {
            string dir = Path.GetDirectoryName(path);
            if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, content, new UTF8Encoding(false));
            if (File.Exists(path))
            {
                try { File.Replace(tmp, path, null); return; }
                catch { /* fall through to delete+move */ }
                File.Delete(path);
            }
            File.Move(tmp, path);
        }
    }
}
