using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;

namespace OniCompanionLink
{
    /// <summary>
    /// set_speed: the game's own speed control (SpeedControlScreen, found by decompiling the Windows build 744825).
    ///   pause -> if not paused: Pause()            (what the pause button does: TogglePause -> Pause(playSound true))
    ///   play  -> speed first: SetSpeed(speed - 1)  (the speed buttons' onClick, 0..2); then, if paused: Unpause()
    ///   speed -> PlaySpeedChangeSound(speed) + SetSpeed(speed - 1), exactly the speed buttons' onClick: the pause state is kept
    /// SpeedControlScreen keeps a pause COUNTER (pauseCount, private; Pause() ++, Unpause() --). Other game code can hold a pause
    /// (screens, dialogs). play is refused when the counter is above 1: one Unpause() would not resume the game and a second would
    /// release a pause that belongs to somebody else. The count is read by reflection (the field is private).
    /// The speed index (GetSpeed) is kept while paused, so "play" without a speed resumes at the game's own speed setting.
    /// A change made in the game itself (keys, buttons, a dialog) is noticed by Tick(): the live file is forced at once. A pause change
    /// already forces a write in LiveWriter.Tick (paused != lastPaused); only the speed number was missing.
    /// </summary>
    internal static class Speed
    {
        private static FieldInfo pauseCountField;
        private static MethodInfo speedSound;      // SpeedControlScreen.PlaySpeedChangeSound(float), what the speed buttons play
        private static bool fieldLooked;
        private static int lastSpeed = -1;

        private static int PauseCount(SpeedControlScreen s)
        {
            if (!fieldLooked)
            {
                fieldLooked = true;
                pauseCountField = typeof(SpeedControlScreen).GetField("pauseCount", BindingFlags.NonPublic | BindingFlags.Instance);
                if (pauseCountField == null) Log.Warn("speed: SpeedControlScreen.pauseCount not found; play only works for a plain pause");
                speedSound = typeof(SpeedControlScreen).GetMethod("PlaySpeedChangeSound", BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(float) }, null);
                if (speedSound == null) Log.Warn("speed: SpeedControlScreen.PlaySpeedChangeSound not found; speed changes are silent");
            }
            if (pauseCountField == null) return s.IsPaused ? 1 : 0;
            try { return (int)pauseCountField.GetValue(s); } catch { return s.IsPaused ? 1 : 0; }
        }

        /// <summary>Main thread, every frame (called from Commands.Pump). A speed change nobody told us about forces a live write.</summary>
        public static void Tick()
        {
            if (!LiveWriter.Ready()) { lastSpeed = -1; return; }
            int sp = SpeedControlScreen.Instance.GetSpeed();
            if (sp != lastSpeed)
            {
                if (lastSpeed >= 0) LiveWriter.MarkSave();
                lastSpeed = sp;
            }
        }

        /// <summary>Runs a set_speed command. state is "pause" or "play"; speed 1..3 or 0 = keep. Returns the ack message.</summary>
        public static bool Apply(string state, int speed, out string message)
        {
            message = null;
            if (!LiveWriter.Ready()) { message = "No colony is loaded"; return false; }
            SpeedControlScreen s = SpeedControlScreen.Instance;
            if (state == "pause")
            {
                if (s.IsPaused) { message = "Already paused"; return true; }
                s.Pause(true, false);
                LiveWriter.MarkSave();
                message = "Paused";
                return true;
            }
            if (state == "speed")
            {
                if (speed < 1 || speed > 3) { message = "Command malformed"; return false; }
                PauseCount(s);                       // looks up the reflection members once
                try { if (speedSound != null) speedSound.Invoke(s, new object[] { (float)speed }); } catch { }
                s.SetSpeed(speed - 1);
                lastSpeed = s.GetSpeed();
                LiveWriter.MarkSave();
                message = "Speed " + (s.GetSpeed() + 1) + (s.IsPaused ? " (still paused)" : "");
                return true;
            }
            if (state != "play") { message = "Command malformed"; return false; }
            if (PauseCount(s) > 1) { message = "The game is held paused by an open screen"; return false; }
            if (speed >= 1 && speed <= 3) s.SetSpeed(speed - 1);
            if (s.IsPaused) s.Unpause(true);
            lastSpeed = s.GetSpeed();
            LiveWriter.MarkSave();
            message = "Playing at speed " + (s.GetSpeed() + 1);
            return true;
        }
    }

    /// <summary>
    /// The game's own UI sprites for the app, written into the theme folder by ThemeWriter (theme.schema.json ModIcon, served as
    /// /api/v1/art/ui/NAME): speedPause, speedPlay, speed1..3 (normal + active look) and the notification icons. Sprites and the tints
    /// the game draws them with are read from the running game, nothing is shipped or hand-picked.
    /// Speed buttons (SpeedControlScreen): each is a KToggle with ImageToggleState components (InactiveSprite/ActiveSprite and
    /// Inactive/ActiveColour on a TargetImage). The first state of a button whose target is not the toggle's own bgImage wins; else
    /// the toggle's fgImage; else the first child Image with a sprite. Pause/play fall back to SpeedControlScreen.pauseIcon / playIcon.
    /// The prefab layout cannot be seen without the running game, so every candidate is logged once ("speed icons:" lines).
    /// Notification icons (NotificationScreen.icon_*), tinted with GetNotificationColour(type), exactly as the alert list draws them.
    /// Main thread: one blit per frame (ThemeWriter steps). All of it is optional: a failure skips the icons, never the theme.
    /// </summary>
    internal static class UiIcons
    {
        private sealed class Job
        {
            public List<string> Names = new List<string>();
            public string File, ActiveFile;
            public Sprite Sprite, ActiveSprite;
            public Color Tint, ActiveTint;
            public byte[] Rgba, ActiveRgba; public int W, H, AW, AH;
        }

        private static readonly List<Job> jobs = new List<Job>();

        public static void Reset() { jobs.Clear(); }

        /// <summary>Theme step: look up the sprites (references only, no drawing) and queue one render step per image.</summary>
        public static void List(System.Action<string, System.Action> add)
        {
            jobs.Clear();
            try { ListSpeed(); } catch (Exception e) { Log.Warn("theme: speed icons skipped: " + e.Message); }
            try { ListAlerts(); } catch (Exception e) { Log.Warn("theme: alert icons skipped: " + e.Message); }
            try { Actions.ListIcons(); } catch (Exception e) { Log.Warn("theme: pad icons skipped: " + e.Message); }
            foreach (Job job in jobs)
            {
                Job jb = job;
                add("icon " + jb.Names[0], delegate ()
                {
                    try
                    {
                        int w, h;
                        byte[] raw = Art.BlitSprite(jb.Sprite, 0, false, out w, out h);
                        if (raw == null) throw new InvalidOperationException("no usable texture rect");
                        jb.Rgba = raw; jb.W = w; jb.H = h;
                    }
                    catch (Exception e) { Log.Warn("theme: icon " + jb.Names[0] + " skipped: " + e.Message); jb.Rgba = null; }
                });
                if (jb.ActiveSprite != null)
                    add("icon " + jb.Names[0] + " active", delegate ()
                    {
                        try
                        {
                            int w, h;
                            byte[] raw = Art.BlitSprite(jb.ActiveSprite, 0, false, out w, out h);
                            if (raw == null) throw new InvalidOperationException("no usable texture rect");
                            jb.ActiveRgba = raw; jb.AW = w; jb.AH = h;
                        }
                        catch (Exception e) { Log.Warn("theme: active icon " + jb.Names[0] + " skipped: " + e.Message); jb.ActiveRgba = null; }
                    });
            }
        }

        // ---- speed control

        private static void ListSpeed()
        {
            SpeedControlScreen s = SpeedControlScreen.Instance;
            if (s == null) return;
            Job pause = PickToggle(s.pauseButtonWidget, "speedPause");
            if (pause == null && s.pauseIcon != null && s.pauseIcon.sprite != null)
                pause = Single("speedPause", s.pauseIcon.sprite, s.pauseIcon.color);
            Add(pause);
            Job play = null;
            if (s.playIcon != null && s.playIcon.sprite != null) play = Single("speedPlay", s.playIcon.sprite, s.playIcon.color);
            if (play == null) play = PickButton(s.playButtonWidget, "speedPlay");
            Add(play);
            Add(PickToggle(s.speedButtonWidget_slow, "speed1"));
            Add(PickToggle(s.speedButtonWidget_medium, "speed2"));
            Add(PickToggle(s.speedButtonWidget_fast, "speed3"));
        }

        private static void Add(Job j) { if (j != null) jobs.Add(j); }

        /// <summary>v1.3: an icon from outside this class (Actions: overlay and tool sprites), drawn and listed like the others.</summary>
        internal static void AddIcon(string name, Sprite sp, Color tint) { Add(Single(name, sp, tint)); }

        private static Job Single(string name, Sprite sp, Color tint)
        {
            Job j = new Job { Sprite = sp, Tint = tint };
            j.Names.Add(name); j.File = name + ".png";
            Log.Info("speed icons: " + name + " from SpeedControlScreen icon image, sprite '" + sp.name + "'");
            return j;
        }

        private static string Path_(Transform t, Transform root)
        {
            string p = t.name;
            for (Transform x = t.parent; x != null && x != root.parent; x = x.parent) p = x.name + "/" + p;
            return p;
        }

        private static Job PickToggle(GameObject widget, string name)
        {
            if (widget == null) { Log.Warn("speed icons: " + name + ": widget missing"); return null; }
            KToggle kt = widget.GetComponent<KToggle>();
            Image bg = kt != null ? kt.bgImage : null;
            foreach (Image im in widget.GetComponentsInChildren<Image>(true))
                if (im != null) Log.Info("speed icons: " + name + " image " + Path_(im.transform, widget.transform) + " sprite '" + (im.sprite != null ? im.sprite.name : "-") + "'" + (im == bg ? " (bgImage)" : ""));
            ImageToggleState pick = null;
            foreach (ImageToggleState its in widget.GetComponentsInChildren<ImageToggleState>(true))
            {
                if (its == null || its.TargetImage == null || !its.useSprites || (its.InactiveSprite == null && its.ActiveSprite == null)) continue;
                if (pick == null || (pick.TargetImage == bg && its.TargetImage != bg)) pick = its;
            }
            if (pick != null)
            {
                Sprite inact = pick.InactiveSprite != null ? pick.InactiveSprite : pick.ActiveSprite;
                Sprite act = pick.ActiveSprite != null ? pick.ActiveSprite : inact;
                Job j = new Job { Sprite = inact, Tint = pick.InactiveColour, ActiveSprite = act, ActiveTint = pick.ActiveColour };
                j.Names.Add(name); j.File = name + ".png"; j.ActiveFile = name + "Active.png";
                Log.Info("speed icons: " + name + " from ImageToggleState on " + Path_(pick.transform, widget.transform) + ": '" + inact.name + "' / active '" + act.name + "'");
                return j;
            }
            if (kt != null && kt.fgImage != null && kt.fgImage.sprite != null)
                return Single(name, kt.fgImage.sprite, kt.fgImage.color);
            foreach (Image im in widget.GetComponentsInChildren<Image>(true))
                if (im != null && im != bg && im.sprite != null && im.gameObject != widget) return Single(name, im.sprite, im.color);
            Log.Warn("speed icons: " + name + ": no sprite found");
            return null;
        }

        private static Job PickButton(GameObject widget, string name)
        {
            if (widget == null) { Log.Warn("speed icons: " + name + ": widget missing"); return null; }
            foreach (Image im in widget.GetComponentsInChildren<Image>(true))
                if (im != null && im.sprite != null && im.gameObject != widget) return Single(name, im.sprite, im.color);
            Image root = widget.GetComponent<Image>();
            if (root != null && root.sprite != null) return Single(name, root.sprite, root.color);
            Log.Warn("speed icons: " + name + ": no sprite found");
            return null;
        }

        // ---- notification icons

        private static void ListAlerts()
        {
            NotificationScreen ns = NotificationScreen.Instance;
            if (ns == null) { Log.Warn("theme: alert icons: NotificationScreen not ready"); return; }
            // names of the contract (IconName); the game draws BadMinor, Good and Neutral with the same icon and color
            AlertIcon(ns, "alertBad", NotificationType.Bad);
            Job shared = AlertIcon(ns, "alertNeutral", NotificationType.Neutral);
            if (shared != null) { shared.Names.Add("alertMinorBad"); shared.Names.Add("alertGood"); }
            AlertIcon(ns, "alertEvent", NotificationType.Event);
            AlertIcon(ns, "alertTutorial", NotificationType.Tutorial);
            AlertIcon(ns, "alertThreatening", NotificationType.DuplicantThreatening);
            AlertIcon(ns, "alertMessage", NotificationType.Messages);
            AlertIcon(ns, "alertMessageImportant", NotificationType.MessageImportant);
        }

        private static Job AlertIcon(NotificationScreen ns, string name, NotificationType type)
        {
            Sprite sp = ns.GetNotificationIcon(type);
            if (sp == null) { Log.Warn("theme: alert icon " + name + ": the game has no sprite"); return null; }
            Job j = new Job { Sprite = sp, Tint = ns.GetNotificationColour(type) };
            j.Names.Add(name); j.File = name + ".png";
            jobs.Add(j);
            return j;
        }

        // ---- writer thread (called from ThemeWriter.Finish's thread, before the theme JSON is closed)

        /// <summary>Encodes and writes the PNGs, then appends the "icons" array. Returns the number of files written.</summary>
        public static int Write(string dir, Json j)
        {
            List<Job> ok = new List<Job>();
            foreach (Job job in jobs) if (job.Rgba != null) ok.Add(job);
            if (ok.Count == 0) return 0;
            int files = 0;
            foreach (Job job in ok)
            {
                Encode(dir, job.File, job.Rgba, job.W, job.H, job.Tint); files++;
                if (job.ActiveRgba == null) job.ActiveFile = null;
                else { Encode(dir, job.ActiveFile, job.ActiveRgba, job.AW, job.AH, job.ActiveTint); files++; }
            }
            j.Key("icons").Arr();
            foreach (Job job in ok)
                foreach (string n in job.Names)
                {
                    j.Obj().P("name", n).P("file", job.File);
                    if (job.ActiveFile != null) j.P("activeFile", job.ActiveFile);
                    j.PI("width", job.W).PI("height", job.H).EndObj();
                }
            j.EndArr();
            return files;
        }

        private static void Encode(string dir, string file, byte[] rgba, int w, int h, Color tint)
        {
            byte[] top = PngCodec.FlipRows(rgba, w, h);
            PngCodec.Tint(top, tint.r, tint.g, tint.b, tint.a);   // the game multiplies a sprite by its Image color
            PngCodec.ClearHidden(top);
            ThemeWriter.WriteBytesAtomic(Path.Combine(dir, file), PngCodec.Encode(w, h, top));
        }
    }
}
