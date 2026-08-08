import json

with open('./pretty_replay/replay.json') as f:
  data = json.load(f)
with open('./pretty_replay/pretty_replay.json', 'w') as f:
  json.dump(data, f, indent=4) 