function updateStatusUi(status) {
  const bridgeStatus = document.getElementById('bridgeStatus');
  const transportMode = document.getElementById('transportMode');
  const inputRateHz = document.getElementById('inputRateHz');

  if (bridgeStatus) {
    bridgeStatus.textContent = status.vrConnected ? 'Client connected' : 'Waiting for headset';
  }
  if (transportMode) {
    transportMode.textContent = status.transportMode || 'waiting-for-client';
  }
  if (inputRateHz) {
    const value = Number(status.inputRateHz || 0);
    inputRateHz.textContent = `${value.toFixed(1)} Hz`;
  }
}

async function pollBridgeStatus() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const status = await response.json();
    updateStatusUi(status);
  } catch (error) {
    const bridgeStatus = document.getElementById('bridgeStatus');
    if (bridgeStatus) {
      bridgeStatus.textContent = 'Status unavailable';
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  pollBridgeStatus();
  window.setInterval(pollBridgeStatus, 2000);
});
