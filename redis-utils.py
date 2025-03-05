import threading
import json
import time
from app import redis_client

class RedisListener:
    """Class to manage real-time Redis channel subscriptions"""
    
    def __init__(self, channels=None):
        self.pubsub = redis_client.pubsub()
        self.channels = channels or []
        self.thread = None
        self.callbacks = {}
        
    def subscribe(self, channel, callback):
        """Subscribe to a channel with a callback function"""
        self.channels.append(channel)
        self.callbacks[channel] = callback
        if self.pubsub.subscribed:
            self.pubsub.subscribe(channel)
            
    def start_listening(self):
        """Start listening for messages in a separate thread"""
        if not self.channels:
            raise ValueError("No channels to subscribe to")
            
        # Subscribe to all channels
        self.pubsub.subscribe(*self.channels)
        
        # Start processing thread
        self.thread = threading.Thread(target=self._process_messages)
        self.thread.daemon = True
        self.thread.start()
        
    def stop_listening(self):
        """Stop listening and clean up"""
        if self.pubsub.subscribed:
            self.pubsub.unsubscribe()
            
        # Set a flag to stop the thread
        self._stop = True
        if self.thread:
            self.thread.join(timeout=1.0)
            
    def _process_messages(self):
        """Process incoming messages and call appropriate callbacks"""
        self._stop = False
        while not self._stop:
            message = self.pubsub.get_message(timeout=1.0)
            if message and message['type'] == 'message':
                channel = message['channel'].decode('utf-8')
                data = json.loads(message['data'].decode('utf-8'))
                
                # Call the appropriate callback for this channel
                if channel in self.callbacks:
                    self.callbacks[channel](data)
                    
            time.sleep(0.01)  # Small sleep to prevent CPU hogging


class RedisCacheManager:
    """Helper class for managing cached data in Redis"""
    
    @staticmethod
    def cache_data(key, data, expiry=3600):
        """Cache data with an expiration time"""
        redis_client.setex(key, expiry, json.dumps(data))
        
    @staticmethod
    def get_cached_data(key):
        """Get cached data if it exists"""
        data = redis_client.get(key)
        if data:
            return json.loads(data.decode('utf-8'))
        return None
        
    @staticmethod
    def invalidate_cache(pattern):
        """Invalidate all cache entries matching a pattern"""
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
            
    @staticmethod
    def increment_counter(key, amount=1):
        """Increment a counter in Redis"""
        return redis_client.incrby(key, amount)


class VotingStatus:
    """Helper class for tracking voting status via Redis"""
    
    @staticmethod
    def set_project_status(project_id, status):
        """Set the status of a project"""
        redis_client.set(f"project:{project_id}:status", status)
        
    @staticmethod
    def get_project_status(project_id):
        """Get the current status of a project"""
        status = redis_client.get(f"project:{project_id}:status")
        return status.decode('utf-8') if status else "pending"
