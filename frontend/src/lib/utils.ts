/**
 * Utility Functions
 * ==================
 * Helper functions for the SARASVATI frontend
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind CSS classes with proper precedence
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format duration in seconds to MM:SS
 */
export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Format confidence score as percentage
 */
export function formatConfidence(confidence: number): string {
  return `${(confidence * 100).toFixed(1)}%`;
}

/**
 * Get severity emoji
 */
export function getSeverityEmoji(severity: string): string {
  const emojiMap: Record<string, string> = {
    critical: "🔴",
    high: "🟠",
    medium: "🟡",
    low: "🟢",
  };
  return emojiMap[severity] || "⚪";
}

/**
 * Debounce function
 */
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null;

  return function executedFunction(...args: Parameters<T>) {
    const later = () => {
      timeout = null;
      func(...args);
    };

    if (timeout) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle function
 */
export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean;

  return function executedFunction(...args: Parameters<T>) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

/**
 * Generate unique ID
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Check if audio is supported
 */
export function isAudioSupported(): boolean {
  return !!(
    typeof window !== "undefined" &&
    (window.AudioContext || (window as any).webkitAudioContext)
  );
}

/**
 * Check if WebRTC is supported
 */
export function isWebRTCSupported(): boolean {
  return !!(
    typeof window !== "undefined" &&
    (navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
  );
}

/**
 * Request notification permission
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (!("Notification" in window)) {
    return false;
  }

  if (Notification.permission === "granted") {
    return true;
  }

  if (Notification.permission !== "denied") {
    const permission = await Notification.requestPermission();
    return permission === "granted";
  }

  return false;
}

/**
 * Play notification sound
 */
export function playNotificationSound(volume: number = 0.3): void {
  try {
    const audio = new Audio("/sounds/notification.mp3");
    audio.volume = volume;
    audio.play().catch(console.error);
  } catch (error) {
    console.warn("Could not play notification sound:", error);
  }
}

/**
 * Copy text to clipboard
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    console.error("Failed to copy to clipboard:", error);
    return false;
  }
}

/**
 * Download data as JSON file
 */
export function downloadJSON(data: any, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filename}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Format error for display
 */
export function formatErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "An unknown error occurred";
}

/**
 * Get connection quality indicator
 */
export function getConnectionQuality(
  latency: number
): "excellent" | "good" | "fair" | "poor" {
  if (latency < 50) return "excellent";
  if (latency < 100) return "good";
  if (latency < 200) return "fair";
  return "poor";
}

/**
 * Calculate audio level from frequency data
 */
export function calculateAudioLevel(dataArray: Uint8Array): number {
  const sum = dataArray.reduce((acc, val) => acc + val, 0);
  return sum / dataArray.length / 255;
}
