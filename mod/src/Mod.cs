using System;
using System.Reflection;
using HarmonyLib;
using KMod;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>Entry point. Files only: no sockets, nothing written into saves.</summary>
    public class OniCompanionLinkMod : UserMod2
    {
        public override void OnLoad(Harmony harmony)
        {
            try
            {
                Log.Info("loading v" + Env.ModVersion + ", output " + Env.CompanionDir() + " (" + (Env.LocalNote ?? "normal mode; " + Env.LocalWhy) + ")");
                Patch(harmony, typeof(MainMenu), "OnSpawn", null, nameof(Patches.MainMenuSpawned));
                Patch(harmony, typeof(Game), "OnSpawn", null, nameof(Patches.GameSpawned));
                Patch(harmony, typeof(Game), "Update", null, nameof(Patches.GameUpdated));
                Patch(harmony, typeof(Game), "OnCleanUp", null, nameof(Patches.GameCleanedUp));
                Patch(harmony, typeof(SaveLoader), "Save", new[] { typeof(string), typeof(bool), typeof(bool) }, nameof(Patches.Saved));
                Patch(harmony, typeof(NotificationManager), "DoAddNotification", null, nameof(Patches.NotificationAdded));
                Patch(harmony, typeof(NotificationManager), "RemoveNotification", null, nameof(Patches.NotificationRemoved));
                Patch(harmony, typeof(PauseScreen), "ConfigureButtonInfos", null, nameof(Patches.PauseButtons));

                Application.quitting += OnQuit;
                LiveWriter.WriteMenu();   // clears a stale "running" file left by a crash
                LiveWriter.StartMenuHeartbeat();
                Commands.Start();
                Sync.Init();
                ConnectWindow.Start();
            }
            catch (Exception e)
            {
                Env.Disable("OnLoad failed", e);
            }
        }

        private static void OnQuit()
        {
            try { LiveWriter.WriteStopped(); } catch { }
            try { Commands.Stop(); } catch { }
            try { ConnectWindow.Stop(); } catch { }
        }

        private static void Patch(Harmony h, Type type, string method, Type[] args, string postfixName)
        {
            MethodBase original = args == null
                ? AccessTools.Method(type, method)
                : AccessTools.Method(type, method, args);
            if (original == null) throw new MissingMethodException(type.Name + "." + method);
            MethodInfo postfix = typeof(Patches).GetMethod(postfixName, BindingFlags.Static | BindingFlags.Public);
            h.Patch(original, null, new HarmonyMethod(postfix));
        }
    }

    // Every hook swallows its own exceptions: a bug here must never reach the game.
    internal static class Patches
    {
        public static void MainMenuSpawned()
        {
            try { Exporter.Run("main menu"); } catch (Exception e) { Env.Disable("MainMenu hook", e); }
            try { Art.Start("main menu"); } catch (Exception e) { Log.Error("art start (main menu)", e); }
        }

        public static void GameSpawned()
        {
            LiveWriter.InGame = true;
            try { Exporter.Run("world load"); } catch (Exception e) { Env.Disable("Game.OnSpawn hook", e); }
            try { Art.Start("world load"); Art.WorldLoaded(); } catch (Exception e) { Log.Error("art start (world load)", e); }
        }

        public static void GameUpdated()
        {
            try { LiveWriter.Tick(); } catch (Exception e) { Env.Disable("Game.Update hook", e); }
            try { Art.Tick(); } catch (Exception e) { Log.Error("art tick", e); }
            try { Commands.Pump(); } catch (Exception e) { Log.Error("Commands.Pump", e); }
            try { ThemeWriter.Tick(); } catch (Exception e) { Log.Error("theme tick", e); }
            try { Sync.Tick(); } catch (Exception e) { Log.Error("sync tick", e); }
            try { ConnectWindow.Tick(); } catch (Exception e) { Log.Error("connect window tick", e); }
        }

        public static void GameCleanedUp()
        {
            LiveWriter.InGame = false;
            try { LiveWriter.OnUnload(); } catch (Exception e) { Log.Error("Game.OnCleanUp hook", e); }
            try { Sync.OnUnload(); } catch { }
            try { ThemeWriter.OnUnload(); } catch { }
            try { ConnectWindow.Close(); } catch { }
        }

        public static void PauseButtons(PauseScreen __instance)
        {
            try { ConnectWindow.AddPauseButton(__instance); } catch (Exception e) { Log.Error("pause button", e); }
        }

        public static void Saved()
        {
            try { LiveWriter.MarkSave(); } catch { }
        }

        public static void NotificationAdded(Notification notification)
        {
            try { LiveWriter.NotificationAdded(notification); } catch { }
        }

        public static void NotificationRemoved(Notification notification)
        {
            try { LiveWriter.NotificationRemoved(notification); } catch { }
        }
    }
}
