import { useState, useEffect, useCallback } from "react";
import api from "../api/client";

export function useTelemetry(intervalMs = 1500) {
  const [thermal, setThermal] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchThermal = useCallback(async () => {
    try {
      const response = await api.get("/system/thermal");
      setThermal(response.data);
    } catch (err) {
      console.error("Thermal telemetry fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchThermal();

    const timer = setInterval(fetchThermal, intervalMs);
    return () => clearInterval(timer);
  }, [fetchThermal, intervalMs]);

  return {
    thermal,
    loading,
    refresh: fetchThermal,
  };
}
