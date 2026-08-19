import matplotlib.pyplot as plt
import numpy as np
import os

# Set a nice style for pitch deck graphics
plt.style.use("seaborn-v0_8-darkgrid")

# Ensure output directory exists
output_dir = "/home/megalith/Desktop/pakhi/pitch_demos"
os.makedirs(output_dir, exist_ok=True)


def generate_market_growth():
    labels = ["2025", "2034 (Projected)"]
    values = [4.6, 9.8]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=["#1f77b4", "#ff7f0e"], width=0.5)

    # Add text labels on top of bars
    for bar in bars:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 0.3,
            f"${yval}B",
            ha="center",
            va="bottom",
            fontsize=14,
            fontweight="bold",
        )

    ax.set_ylabel("Market Size (Billions USD)", fontsize=12, fontweight="bold")
    ax.set_title(
        "Graph 3: Explosive Market Growth\n(Weather Derivatives)",
        fontsize=16,
        fontweight="bold",
        pad=20,
    )

    # Tweak axes
    ax.set_ylim(0, 12)
    plt.xticks(fontsize=14, fontweight="bold")
    plt.yticks(fontsize=12)

    output_path = os.path.join(output_dir, "Graph_3_Market_Growth.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved: {output_path}")


def generate_target_sectors():
    labels = ["Energy", "Agriculture", "Insurance &\nReinsurance", "Other Sectors"]
    sizes = [44.1, 18.7, 14.3, 22.9]
    colors = ["#2ca02c", "#ff7f0e", "#1f77b4", "#7f7f7f"]
    explode = (0.05, 0, 0, 0)  # slightly "explode" the Energy slice

    fig, ax = plt.subplots(figsize=(8, 6))

    # Create donut chart
    wedges, texts, autotexts = ax.pie(
        sizes,
        explode=explode,
        labels=labels,
        colors=colors,
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.85,
        textprops={"fontsize": 12, "fontweight": "bold"},
    )

    # Draw circle in the center to make it a donut
    centre_circle = plt.Circle((0, 0), 0.70, fc="white")
    fig.gca().add_artist(centre_circle)

    # Style the percentages
    for autotext in autotexts:
        autotext.set_color("white")

    ax.set_title("Graph 4: Our Target Sectors", fontsize=16, fontweight="bold", pad=20)

    # Equal aspect ratio ensures that pie is drawn as a circle
    ax.axis("equal")

    output_path = os.path.join(output_dir, "Graph_4_Target_Sectors.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    print("Generating Graph 3 & 4...")
    generate_market_growth()
    generate_target_sectors()
    print("Complete.")
