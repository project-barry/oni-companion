using System;
using System.IO;
using OniCompanionLink;

// Composes sample files with the same Json calls and the same header + Raw(content) pattern as LiveWriter,
// so mod/check_output.py can validate the shape against the frozen schemas.
internal static class Program
{
    private static int Main(string[] args)
    {
        string dir = args.Length > 0 ? args[0] : ".";
        Directory.CreateDirectory(dir);

        Json c = new Json();
        c.Obj();
        c.PI("build", 744825);
        c.Key("dlcIds").StrArr(new[] { "EXPANSION1_ID", "DLC2_ID" });
        c.P("colonyName", "Sample \"Colony\"\nline");
        c.P("colonyGuid", "00000000-0000-0000-0000-000000000001");
        c.PI("cycle", 12).P("timeOfDay", 0.4237).P("paused", false).PI("speed", 2).PI("activeWorldId", 0);
        c.Key("worlds").Arr();
        c.Obj().PI("id", 0).P("name", "Home").P("isStarter", true);
        c.Key("dupes").Arr();
        Json d = new Json();
        d.Obj().P("id", "123").P("name", "Ada").P("stress", 12.5);
        d.Key("health").Obj().P("value", 100).P("max", 100).EndObj();
        d.Key("calories").Obj().P("value", 3200.123456789).P("max", 4000).EndObj();
        d.Key("breath").Obj().P("value", 100).P("max", 100).EndObj();
        d.P("bladder", 10);
        d.Key("morale").Obj().P("value", 12).P("required", 8).EndObj();
        d.Key("chore").Null();
        d.Key("skills").StrArr(new[] { "Mining1" });
        d.Key("traits").StrArr(new string[0]);
        d.Key("assignedSkill").Str("Miner");
        d.EndObj();
        c.Raw0(d.ToString());
        c.EndArr();
        c.Key("resources").Obj().P("Algae", 12.5).P("Water", 1000).EndObj();
        c.Key("critters").Arr().Obj().P("id", "Hatch").PI("count", 3).PI("tame", 2).EndObj().EndArr();
        c.Key("alerts").Arr().Obj().P("id", "k").P("level", "bad").P("text", "No Oxygen").PI("cycle", 12).PI("count", 2).EndObj().EndArr();
        Json r = new Json();
        r.Obj().Key("current").Null().Key("queue").Arr().EndArr().Key("completed").StrArr(new[] { "FarmingTech" }).EndObj();
        c.Key("research").Raw0(r.ToString());
        c.EndObj().EndArr().EndObj();
        string content = c.ToString();
        content = content.Substring(1, content.Length - 2);

        Json j = new Json();
        j.Obj().PI("schema", 1).PI("seq", 1).P("state", "running").P("writtenAt", "2026-10-25T12:00:00Z").P("modVersion", "0.1.0");
        j.P("writeMs", 0.812);
        j.Raw(content);
        j.EndObj();
        File.WriteAllText(Path.Combine(dir, "live-running.json"), j.ToString());

        Json m = new Json();
        m.Obj().PI("schema", 1).PI("seq", 2).P("state", "menu").P("writtenAt", "2026-10-25T12:00:05Z").P("modVersion", "0.1.0").EndObj();
        File.WriteAllText(Path.Combine(dir, "live-menu.json"), m.ToString());
        return 0;
    }
}
