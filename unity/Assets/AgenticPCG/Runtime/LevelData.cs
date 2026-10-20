using System;
using UnityEngine;

namespace AgenticPCG
{
    [Serializable]
    public class LevelData
    {
        public int schema_version;
        public string[] rows;
        public int Width => rows[0].Length;
        public int Height => rows.Length;

        public void Validate()
        {
            if (schema_version != 1 || rows == null || rows.Length < 5 || rows.Length > 64)
                throw new ArgumentException("Invalid level schema or height");
            if (rows[0] == null || Width < 5 || Width > 64)
                throw new ArgumentException("Invalid level width");
            int players = 0, keys = 0, doors = 0;
            for (int y = 0; y < Height; y++)
            {
                if (rows[y] == null || rows[y].Length != Width)
                    throw new ArgumentException("Rows must be rectangular");
                for (int x = 0; x < Width; x++)
                {
                    char c = rows[y][x];
                    if ("#.PKDH".IndexOf(c) < 0) throw new ArgumentException("Unknown tile");
                    if ((x == 0 || y == 0 || x == Width - 1 || y == Height - 1) && c != '#')
                        throw new ArgumentException("Boundary must be walls");
                    if (c == 'P') players++;
                    if (c == 'K') keys++;
                    if (c == 'D') doors++;
                }
            }
            if (players != 1 || keys != 1 || doors != 1)
                throw new ArgumentException("Exactly one P/K/D required");
        }

        public Vector2 Position(char tile)
        {
            for (int y = 0; y < Height; y++)
                for (int x = 0; x < Width; x++)
                    if (rows[y][x] == tile) return new Vector2(x, -y);
            throw new ArgumentException("Tile missing");
        }
    }

    [Serializable]
    public struct GridPoint
    {
        public int x, y;
        public Vector2 World => new Vector2(x, -y);
    }

    [Serializable]
    public class BridgeJob
    {
        public string request_id, level_digest;
        public int owner_pid;
        public LevelData level;
        public GridPoint[] route;
    }

    [Serializable]
    public class PhysicsReport
    {
        public string request_id, level_digest;
        public string backend = "unity-physics-editmode";
        public bool won, has_key, dead;
        public int physics_steps, wall_contacts, colliders;
        public float simulation_seconds;
        public double evaluation_seconds;
        public string error = "";
        public string unity_version;
    }
}
