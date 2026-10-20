using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace AgenticPCG.Editor
{
    public static class LevelMenu
    {
        [MenuItem("Agentic PCG/Import Level JSON for Play")]
        public static void Import()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            string path = EditorUtility.OpenFilePanel("Import generated level", Path.GetFullPath("../runs"), "json");
            if (path == "") return;
            string json = File.ReadAllText(path);
            JsonUtility.FromJson<LevelData>(json).Validate();
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var root = new GameObject("Level Bootstrap");
            root.AddComponent<LevelBootstrap>().levelJson = json;
            Directory.CreateDirectory("Assets/Generated");
            AssetDatabase.Refresh();
            EditorSceneManager.SaveScene(scene, AssetDatabase.GenerateUniqueAssetPath("Assets/Generated/Level.unity"));
            Selection.activeGameObject = root;
            Debug.Log("Level imported. Press Play; inspect Generated Level in Hierarchy. WASD/arrows to move.");
        }

        [MenuItem("Agentic PCG/Add Current Scene to Build")]
        public static void AddToBuild()
        {
            var scene = SceneManager.GetActiveScene();
            if (string.IsNullOrEmpty(scene.path)) { Debug.LogError("Save the scene first."); return; }
            var list = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            list.RemoveAll(s => s.path == scene.path);
            list.Insert(0, new EditorBuildSettingsScene(scene.path, true));
            EditorBuildSettings.scenes = list.ToArray();
        }
    }
}
