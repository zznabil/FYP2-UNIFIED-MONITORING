
## Requirements
- Telegraf 1.32.3 or later
- Prometheus 2.55.1 or later
- Grafana (latest version)

## Directory Structure
```
telegraf-method/
├── telegraf.conf      # Telegraf configuration
├── prometheus.yml     # Prometheus configuration
└── README.md         # This file
```

## Setup Instructions

1. Start Telegraf:
   ```
   telegraf.exe --config telegraf.conf
   ```

2. Start Prometheus:
   ```
   prometheus.exe --config.file=prometheus.yml
   ```

3. Verify metrics:
   - Telegraf metrics: http://localhost:9273/metrics
   - Prometheus interface: http://localhost:9090

## Metrics Collected
- System Information:
  - System Uptime
  - System Name
  - System Description
- Interface Metrics (FastEthernet0/1 and 0/2):
  - Interface Status
  - Input Octets
  - Output Octets

## Ports Used
- Telegraf: 9273 (Prometheus output)
- Prometheus: 9090 (Web interface)
