using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace AgenticPCG
{
    public static class LevelBuilder
    {
        public static PlayerMotor Build(LevelData level, Scene scene, bool visuals, int layer = 0)
        {
            level.Validate();
            var root = new GameObject("Generated Level");
            SceneManager.MoveGameObjectToScene(root, scene);
            var walls = new List<Collider2D>();
            var hazards = new List<Collider2D>();
            PlayerMotor player = null;
            Collider2D key = null, door = null;
            // Load art once per visible map; physics-only replays do not load textures.
            var art = new Dictionary<char, Sprite>();
            if (visuals)
                foreach (var entry in new[] { ('#', "solid"), ('.', "empty"), ('P', "player"),
                    ('K', "key"), ('D', "door"), ('H', "bat") })
                {
                    var sprite = Resources.Load<Sprite>("Keydoor/" + entry.Item2);
                    if (sprite == null) throw new System.InvalidOperationException("Missing sprite: " + entry.Item2);
                    art[entry.Item1] = sprite;
                }
            for (int y = 0; y < level.Height; y++)
            {
                for (int x = 0; x < level.Width; x++)
                {
                    char tile = level.rows[y][x];
                    var go = new GameObject($"{tile} ({x},{y})");
                    SceneManager.MoveGameObjectToScene(go, scene);
                    go.layer = layer;
                    go.transform.SetParent(root.transform);
                    go.transform.position = new Vector3(x, -y, 0);
                    if (visuals)
                    {
                        // Floor stays under entities and after key pickup; colliders stay on the root.
                        var floor = tile == 'K' || tile == 'P' ? new GameObject($"Floor ({x},{y})") : go;
                        if (tile == 'K' || tile == 'P')
                        {
                            SceneManager.MoveGameObjectToScene(floor, scene);
                            floor.transform.SetParent(root.transform);
                            floor.transform.position = go.transform.position;
                        }
                        AddSprite(floor, art[tile == '#' ? '#' : '.'], 0);
                        if (tile != '#' && tile != '.') AddSprite(go, art[tile], tile == 'P' ? 2 : 1);
                    }
                    if (tile == '.') continue;
                    var collider = go.AddComponent<BoxCollider2D>();
                    // Explicit collider dimensions independent of whether rendering is enabled.
                    collider.size = Vector2.one * (tile == 'P' ? .6f : 1f);
                    collider.isTrigger = tile == 'K' || tile == 'H';
                    if (tile == '#') walls.Add(collider);
                    if (tile == 'H') hazards.Add(collider);
                    if (tile == 'K') key = collider;
                    if (tile == 'D') door = collider;
                    if (tile == 'P')
                    {
                        var body = go.AddComponent<Rigidbody2D>();
                        body.bodyType = RigidbodyType2D.Dynamic; // Wall collisions must stop the player.
                        body.gravityScale = 0;
                        body.constraints = RigidbodyConstraints2D.FreezeRotation;
                        body.collisionDetectionMode = CollisionDetectionMode2D.Continuous;
                        body.sleepMode = RigidbodySleepMode2D.NeverSleep;
                        player = go.AddComponent<PlayerMotor>();
                        player.body = body;
                        player.playerCollider = collider;
                    }
                }
            }
            player.keyCollider = key;
            player.doorCollider = door;
            player.walls = walls.ToArray();
            player.hazards = hazards.ToArray();
            player.manualInput = visuals;
            if (visuals)
            {
                var cameraObject = new GameObject("Main Camera");
                SceneManager.MoveGameObjectToScene(cameraObject, scene);
                cameraObject.transform.SetParent(root.transform);
                cameraObject.tag = "MainCamera";
                cameraObject.transform.position = new Vector3((level.Width - 1) / 2f, -(level.Height - 1) / 2f, -10);
                var camera = cameraObject.AddComponent<Camera>();
                camera.orthographic = true;
                camera.orthographicSize = Mathf.Max(level.Height / 2f + 1, level.Width / (2f * camera.aspect) + 1);
                camera.backgroundColor = new Color(.05f, .08f, .14f);
                camera.clearFlags = CameraClearFlags.SolidColor;
            }
            return player;
        }

        static void AddSprite(GameObject parent, Sprite sprite, int order)
        {
            var visual = new GameObject("Sprite");
            SceneManager.MoveGameObjectToScene(visual, parent.scene);
            visual.layer = parent.layer;
            visual.transform.SetParent(parent.transform, false);
            var renderer = visual.AddComponent<SpriteRenderer>();
            renderer.sprite = sprite;
            renderer.sortingOrder = order;
        }
    }
}
