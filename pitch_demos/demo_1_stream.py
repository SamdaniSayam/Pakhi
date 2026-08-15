import time
import json
import random
from rich.console import Console

console = Console()

def run_stream():
    console.print("[bold green]Connecting to Pakhi WebSocket API (wss://api.pakhi.io/v1/stream)...[/bold green]")
    time.sleep(1)
    console.print("[bold green]Connected.[/bold green]\n")
    
    assets = ["OJ_FUTURES", "NG_FUTURES", "ERCOT_POWER", "WHEAT_FUTURES"]
    
    try:
        while True:
            payload = {
                "timestamp": time.time(),
                "asset": random.choice(assets),
                "probability": round(random.uniform(0.1, 0.95), 2),
                "latency_ms": random.randint(15, 60)
            }
            if payload["probability"] > 0.8:
                payload["signal"] = "LONG"
                color = "bold green"
            elif payload["probability"] < 0.2:
                payload["signal"] = "SHORT"
                color = "bold red"
            else:
                payload["signal"] = "HOLD"
                color = "cyan"
                
            console.print(f"[{color}]{json.dumps(payload)}[/{color}]")
            time.sleep(random.uniform(0.1, 0.4))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Stream disconnected.[/bold yellow]")

if __name__ == "__main__":
    run_stream()
