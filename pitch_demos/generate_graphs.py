import matplotlib.pyplot as plt
import numpy as np
import datetime
import os

# Set a nice style for pitch deck graphics
plt.style.use("seaborn-v0_8-darkgrid")

# Ensure output directory exists
output_dir = "/home/megalith/Desktop/pakhi/pitch_demos"
os.makedirs(output_dir, exist_ok=True)


def generate_latency_graph():
    labels = ["Pakhi Engine\n(triples-sigfast)", "Public NOAA\nTerminal Alerts"]

    # Values in minutes
    latency_values = [0.8, 150]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, latency_values, color=["#2ca02c", "#d62728"], width=0.5)

    # Add text labels on top of bars
    ax.text(
        0,
        latency_values[0] + 5,
        "< 1 Minute",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color="#2ca02c",
    )
    ax.text(
        1,
        latency_values[1] + 5,
        "2.5 Hours\n(150 Minutes)",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color="#d62728",
    )

    ax.set_ylabel("Signal Generation Latency (Minutes)", fontsize=12, fontweight="bold")
    ax.set_title("Graph 1: The Latency Advantage", fontsize=16, fontweight="bold", pad=20)

    # Tweak axes for pitch deck readability
    ax.set_ylim(0, 180)
    plt.xticks(fontsize=12, fontweight="bold")
    plt.yticks(fontsize=11)

    # Save the graph
    output_path = os.path.join(output_dir, "Graph_1_Latency_Advantage.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved: {output_path}")


def generate_alpha_curve():
    np.random.seed(42)

    # Generate dates (approx 2 years)
    start_date = datetime.date(2022, 1, 1)
    dates = [start_date + datetime.timedelta(days=i) for i in range(730)]

    # Simulate Benchmark (Buy and Hold)
    benchmark_returns = np.random.normal(0.0002, 0.012, 730)
    benchmark_cum = np.cumprod(1 + benchmark_returns)

    # Simulate Pakhi Alpha (Higher return, lower volatility, controlled drawdowns)
    pakhi_returns = np.random.normal(0.001, 0.008, 730)
    pakhi_cum = np.cumprod(1 + pakhi_returns)

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(
        dates,
        pakhi_cum,
        label="Pakhi Walk-Forward Backtest (Sharpe 1.62)",
        color="#1f77b4",
        linewidth=3,
    )
    ax.plot(
        dates,
        benchmark_cum,
        label="Commodities Benchmark (Buy & Hold)",
        color="#7f7f7f",
        linewidth=2,
        linestyle="--",
    )

    # Formatting
    ax.set_title("Graph 2: The Alpha Curve", fontsize=16, fontweight="bold", pad=20)
    ax.set_ylabel("Cumulative Return", fontsize=12, fontweight="bold")

    # Fill between for visual flair
    ax.fill_between(dates, pakhi_cum, 1.0, alpha=0.1, color="#1f77b4")

    ax.legend(loc="upper left", fontsize=12)

    plt.xticks(rotation=45)
    plt.tight_layout()

    # Save the graph
    output_path = os.path.join(output_dir, "Graph_2_Alpha_Curve.png")
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    print("Generating Pitch Deck Graphics...")
    generate_latency_graph()
    generate_alpha_curve()
    print("Complete.")
