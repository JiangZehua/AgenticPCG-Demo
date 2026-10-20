using UnityEngine;

namespace AgenticPCG
{
    // Embedded JSON lets the map play without Python; generation uses the optional local worker.
    public class LevelBootstrap : MonoBehaviour
    {
        [TextArea(5, 20)] public string levelJson;

        void Start()
        {
            var data = JsonUtility.FromJson<LevelData>(levelJson);
            var player = LevelBuilder.Build(data, gameObject.scene, true);
            gameObject.AddComponent<GenerationPanel>().SetLevel(data, player);
        }
    }
}
