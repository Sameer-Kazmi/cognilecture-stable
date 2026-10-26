import subprocess
import json
import time
import os
import random
import threading
import psutil
import numpy as np
from typing import Dict, Any, List
from config import (
    OLLAMA_MODEL,
    OLLAMA_COMPACT_MODEL,
    OLLAMA_MODELS_URL,
)

# Thermal threshold definitions in Celsius
TEMP_SAFE_THRESHOLD = 60.0
TEMP_THROTTLE_THRESHOLD = 75.0

class HardwareThermalSensor:
    """
    ESTIMATED thermal sensor. It does NOT read hardware: the temperature is
    baseline + 0.15 x CPU load (+ small noise). The two demo toggles set fixed
    high values (simulated spike / CPU-burn ramp) so the model-switching logic
    can be demonstrated. Replace get_hardware_telemetry() with a real sensor
    reader (e.g. psutil.sensors_temperatures on Linux) to make it physical.
    """
    def __init__(self):
        self._baseline_temp = 48.0
        self._current_temp = 48.0
        self._last_read_time = 0.0
        self._cache_duration = 1.0
        self._simulated_spike = False

        # Real physical CPU hardware burn workers
        self._physical_stress_active = False
        self._stress_threads: List[threading.Thread] = []
        self._stress_stop_event = threading.Event()

    def toggle_simulated_spike(self, enabled: bool):
        self._simulated_spike = enabled
        self._last_read_time = 0.0
        if enabled:
            # Immediately enter critical throttling zone for immediate feedback
            self._current_temp = max(self._current_temp, 82.5)
            self._last_reading = self._current_temp
        else:
            self._current_temp = self._baseline_temp
            self._last_reading = self._baseline_temp

    def is_spike_simulated(self) -> bool:
        return self._simulated_spike

    def is_physical_stress_active(self) -> bool:
        return self._physical_stress_active

    def toggle_physical_stress(self, enabled: bool) -> bool:
        """
        Starts or stops real multi-threaded matrix operations across CPU cores.
        Spins intensive unthrottled dot-products to genuinely draw electrical power and elevate temperature.
        """
        self._last_read_time = 0.0
        if enabled and not self._physical_stress_active:
            self._physical_stress_active = True
            self._stress_stop_event.clear()
            num_workers = max(4, (os.cpu_count() or 4))

            def _matrix_burn():
                a = np.random.rand(1200, 1200).astype(np.float32)
                b = np.random.rand(1200, 1200).astype(np.float32)
                while not self._stress_stop_event.is_set():
                    _ = np.dot(a, b)

            self._stress_threads = [
                threading.Thread(target=_matrix_burn, daemon=True)
                for _ in range(num_workers)
            ]
            for t in self._stress_threads:
                t.start()

            # Immediate jump into elevated warm on first tick, ramping up to throttling
            self._current_temp = max(self._current_temp, 72.5)
            self._last_reading = self._current_temp

        elif not enabled and self._physical_stress_active:
            self._physical_stress_active = False
            self._stress_stop_event.set()
            for t in self._stress_threads:
                t.join(timeout=0.3)
            self._stress_threads = []
            self._current_temp = self._baseline_temp + 2.0
            self._last_reading = self._current_temp

        return self._physical_stress_active

    def get_hardware_telemetry(self) -> dict:
        now = time.time()
        cpu_load = psutil.cpu_percent(interval=None)

        # 1. Update progressive simulated thermal curve if simulated spike is active
        if self._simulated_spike:
            target = 82.5 + random.uniform(-0.6, 1.4)
            self._current_temp = round(target, 1)
            simulated_load = round(92.0 + random.uniform(-2.0, 5.0), 1)
            self._last_reading = self._current_temp
            self._last_read_time = now

            return {
                "primary_temp_c": self._current_temp,
                "zones": [
                    {"Zone": "est.core_0 (SIMULATED)", "TempC": self._current_temp},
                    {"Zone": "est.package_0 (SIMULATED)", "TempC": round(self._current_temp + 2.1, 1)}
                ],
                "cpu_load_percent": simulated_load,
                "throttling_risk": "CRITICAL_THROTTLING",
                "simulated": True,
                "physical_stress_active": self._physical_stress_active,
                "timestamp": now
            }

        # 2. Real physical stress burn active
        if self._physical_stress_active:
            # Smoothly ramp toward 83.5°C
            target = 83.5 + random.uniform(-0.8, 2.0)
            if self._current_temp < 80.0:
                self._current_temp = round(self._current_temp + random.uniform(3.0, 5.5), 1)
            else:
                self._current_temp = round(target, 1)

            actual_load = max(round(cpu_load, 1), round(94.0 + random.uniform(0.0, 5.8), 1))
            self._last_reading = self._current_temp
            self._last_read_time = now

            risk = "CRITICAL_THROTTLING" if self._current_temp >= TEMP_THROTTLE_THRESHOLD else "ELEVATED_WARM"

            return {
                "primary_temp_c": self._current_temp,
                "zones": [
                    {"Zone": "est.core (CPU BURN, ramped value)", "TempC": self._current_temp},
                    {"Zone": "est.die", "TempC": round(self._current_temp + 1.8, 1)}
                ],
                "cpu_load_percent": actual_load,
                "throttling_risk": risk,
                "simulated": False,
                "physical_stress_active": True,
                "timestamp": now
            }

        # 3. Normal physical state: cool down to baseline if it was high
        if self._current_temp > self._baseline_temp + 1.5:
            self._current_temp = round(max(self._baseline_temp, self._current_temp - random.uniform(3.0, 5.0)), 1)
            self._last_reading = self._current_temp

        if now - self._last_read_time > self._cache_duration:
            actual_load = round(cpu_load, 1)
            est_temp = round(self._baseline_temp + (actual_load * 0.15) + random.uniform(-0.3, 0.3), 1)
            self._current_temp = est_temp
            self._last_reading = est_temp
            self._zones = [
                {"Zone": "est.core", "TempC": self._current_temp},
                {"Zone": "est.die", "TempC": round(self._current_temp + 1.2, 1)}
            ]
            self._last_read_time = now

        if self._last_reading >= TEMP_THROTTLE_THRESHOLD:
            risk = "CRITICAL_THROTTLING"
        elif self._last_reading >= TEMP_SAFE_THRESHOLD:
            risk = "ELEVATED_WARM"
        else:
            risk = "OPTIMAL_SAFE"

        return {
            "primary_temp_c": self._last_reading,
            "zones": getattr(self, "_zones", [{"Zone": "est.core", "TempC": self._last_reading}]),
            "cpu_load_percent": round(cpu_load, 1),
            "throttling_risk": risk,
            "simulated": False,
            "physical_stress_active": False,
            "timestamp": now
        }

class ThermalRLAgent:
    """
    Reinforcement Learning (Q-learning) Agent that monitors physical thermal state
    and dynamically selects between configured Ollama model tiers.
    """
    def __init__(
        self,
        full_model=OLLAMA_MODEL,
        quantized_model=OLLAMA_COMPACT_MODEL,
    ):
        self.sensor = HardwareThermalSensor()
        self.full_model = full_model
        self.quantized_model = quantized_model

        # State space: 0: OPTIMAL (<60C), 1: WARM (60C-75C), 2: CRITICAL (>=75C)
        # Action space: 0: FULL_MODEL, 1: QUANTIZED_MODEL
        self.q_table = {
            0: {0: 1.0, 1: 0.5},   # In optimal state, full model is preferred
            1: {0: 0.9, 1: 0.8},   # Warm: keep the primary model; only CRITICAL switches
            2: {0: -2.0, 1: 1.5}   # In throttling state, heavy penalty for full model!
        }
        self.learning_rate = 0.1
        self.discount_factor = 0.9
        self.last_state = 0
        self.last_action = 0

    def _get_state_index(self, temp_c: float) -> int:
        if temp_c >= TEMP_THROTTLE_THRESHOLD:
            return 2 # CRITICAL
        elif temp_c >= TEMP_SAFE_THRESHOLD:
            return 1 # WARM
        return 0     # OPTIMAL

    _avail_cache = (0.0, None)

    def _compact_available(self) -> bool:
        """Is the compact model pulled in Ollama? Cached for 30 s so polling stays cheap."""
        now = time.time()
        ts, ok = self._avail_cache
        if ok is not None and now - ts < 30:
            return ok
        try:
            import urllib.request
            with urllib.request.urlopen(OLLAMA_MODELS_URL, timeout=0.5) as resp:
                ids = [m.get("id") for m in json.loads(resp.read().decode("utf-8")).get("data", [])]
            ok = self.quantized_model in ids
        except Exception:
            ok = False
        self._avail_cache = (now, ok)
        return ok

    def select_model(self, learn: bool = True) -> dict:
        """
        Observe the (estimated) temperature and pick a model tier.
        learn=False is for read-only callers such as the dashboard poll: it must
        not change the Q-table.
        """
        telemetry = self.sensor.get_hardware_telemetry()
        state_idx = self._get_state_index(telemetry["primary_temp_c"])

        actions = self.q_table[state_idx]
        chosen_action = max(actions, key=actions.get)   # greedy

        fallback = False
        if chosen_action == 1 and not self._compact_available():
            selected_model, fallback = self.full_model, True
        else:
            selected_model = self.quantized_model if chosen_action == 1 else self.full_model
        tier = "COMPACT" if selected_model == self.quantized_model and chosen_action == 1 else "PRIMARY"
        model_tier = f"{tier} ({selected_model})" + (" - compact model not installed, using primary" if fallback else "")

        if learn:
            if state_idx == 2 and chosen_action == 0:
                reward = -2.5
            elif state_idx == 2 and chosen_action == 1:
                reward = 1.8
            elif state_idx == 0 and chosen_action == 0:
                reward = 1.5
            else:
                reward = 0.8
            old_val = self.q_table[state_idx][chosen_action]
            next_max = max(self.q_table[state_idx].values())
            self.q_table[state_idx][chosen_action] = old_val + self.learning_rate * (reward + self.discount_factor * next_max - old_val)

        return {
            "selected_model": selected_model,
            "model_tier": model_tier,
            "action_id": chosen_action,
            "fallback": fallback,
            "state_index": state_idx,
            "telemetry": telemetry,
            "q_values": self.q_table[state_idx],
        }


# Global singleton
thermal_agent = ThermalRLAgent()
