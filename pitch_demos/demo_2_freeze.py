import time
from rich.console import Console
from rich.table import Table

console = Console()


def run_freeze_demo():
    console.print("[bold cyan]Loading Historical Data: Florida Freeze (Dec 2022)[/bold cyan]")
    time.sleep(1)

    table = Table(title="Pakhi vs Market Reaction (Orange Juice Futures)")
    table.add_column("Timeline", style="cyan")
    table.add_column("Event", style="magenta")
    table.add_column("Market Price (OJ)", justify="right", style="green")

    events = [
        ("T - 5 Days", "GFS Model shows minor temp drop", "$2.10"),
        ("T - 4 Days", "Pakhi Engine detects ENSO anomaly", "$2.11"),
        ("T - 3 Days", "[bold red]Pakhi fires LONG Signal (Prob: 88%)[/bold red]", "$2.12"),
        ("T - 2 Days", "Market ignores weather, no movement", "$2.12"),
        ("T - 0 Days", "Freeze Hits Florida Groves", "$2.15"),
        ("T + 1 Days", "News Reports Crop Damage", "$2.45"),
        ("T + 2 Days", "Market Prices in Freeze (Surge)", "[bold green]$2.80[/bold green]"),
    ]

    for timeline, event, price in events:
        table.add_row(timeline, event, price)
        console.clear()
        console.print("[bold cyan]Loading Historical Data: Florida Freeze (Dec 2022)[/bold cyan]\n")
        console.print(table)
        time.sleep(1.5)

    console.print(
        "\n[bold yellow]Result: Signal generated 3 days before market price-in.[/bold yellow]"
    )
    console.print("[bold green]This is the alpha we are selling to commodity traders.[/bold green]")


if __name__ == "__main__":
    run_freeze_demo()
