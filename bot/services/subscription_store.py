import json
import os
from typing import Dict, List, Set


class SubscriptionStore:
	def __init__(self, storage_path: str = "data/subscriptions.json") -> None:
		self.storage_path = storage_path
		self.channel_to_keys: Dict[int, Set[str]] = {}
		self._ensure_storage_dir()
		self.load()

	def _ensure_storage_dir(self) -> None:
		directory = os.path.dirname(self.storage_path)
		if directory and not os.path.exists(directory):
			os.makedirs(directory, exist_ok=True)

	def load(self) -> None:
		if not os.path.exists(self.storage_path):
			self.channel_to_keys = {}
			return
		with open(self.storage_path, "r", encoding="utf-8") as f:
			data = json.load(f)
			self.channel_to_keys = {int(k): set(v) for k, v in data.items()}

	def save(self) -> None:
		serializable: Dict[str, List[str]] = {str(k): sorted(list(v)) for k, v in self.channel_to_keys.items()}
		with open(self.storage_path, "w", encoding="utf-8") as f:
			json.dump(serializable, f, ensure_ascii=False, indent=2)

	def get_channels(self) -> List[int]:
		return list(self.channel_to_keys.keys())

	def get_subscriptions(self, channel_id: int) -> List[str]:
		return sorted(list(self.channel_to_keys.get(channel_id, set())))

	def add_subscription(self, channel_id: int, key: str) -> bool:
		key = key.strip()
		if not key:
			return False
		if channel_id not in self.channel_to_keys:
			self.channel_to_keys[channel_id] = set()
		before = len(self.channel_to_keys[channel_id])
		self.channel_to_keys[channel_id].add(key)
		after = len(self.channel_to_keys[channel_id])
		self.save()
		return after > before

	def remove_subscription(self, channel_id: int, key: str) -> bool:
		key = key.strip()
		if not key:
			return False
		if channel_id not in self.channel_to_keys:
			return False
		if key in self.channel_to_keys[channel_id]:
			self.channel_to_keys[channel_id].remove(key)
			if not self.channel_to_keys[channel_id]:
				self.channel_to_keys.pop(channel_id, None)
			self.save()
			return True
		return False

	def clear_channel(self, channel_id: int) -> int:
		items_cleared = len(self.channel_to_keys.get(channel_id, set()))
		if channel_id in self.channel_to_keys:
			self.channel_to_keys.pop(channel_id)
			self.save()
		return items_cleared