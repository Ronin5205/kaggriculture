def agent(obs):
    farms = obs.get("farms", [])
    player = obs.get("player", 0)
    private = obs.get("private", {}) or {}
    return {"farmer": "PASS", "hands": [], "market": []}