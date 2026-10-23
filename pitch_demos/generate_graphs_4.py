import matplotlib.pyplot as plt
import os

# Set a nice style for pitch deck graphics
plt.style.use("seaborn-v0_8-darkgrid")

# Ensure output directory exists
output_dir = "/home/megalith/Desktop/pakhi/pitch_demos"
os.makedirs(output_dir, exist_ok=True)


def generate_business_model():
    fig, ax = plt.subplots(figsize=(10, 7))

    tiers = ["Tier 1\nCommunity Edition", "Tier 2\nManaged API", "Tier 3\nEnterprise Contracts"]

    # Using relative heights for visual stepping, since Tier 1 is $0
    # Giving Tier 1 a small height just so there is a visual base.
    values = [1000, 5000, 12000]
    colors = ["#7f7f7f", "#1f77b4", "#2ca02c"]

    bars = ax.bar(tiers, values, color=colors, width=0.6, edgecolor="white", linewidth=2)

    labels = [
        "Forever Free\n\nGrassroots dev adoption\nLead Generation",
        "$1,500 - $5,000 / mo\n\nManaged API access\nPer instrument feed",
        "$10,000+ / mo\n\nDedicated infrastructure\nCloud backtesting\nStrict SLAs",
    ]

    for i, bar in enumerate(bars):
        yval = bar.get_height()
        # Add the explanatory labels inside/above the bars
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 500,
            labels[i],
            ha="center",
            va="bottom",
            fontsize=13,
            fontweight="bold",
            color="#333333",
            bbox=dict(
                facecolor="white",
                alpha=0.9,
                edgecolor=colors[i],
                boxstyle="round,pad=0.8",
                linewidth=2,
            ),
        )

    ax.set_title("Graph 6: Enterprise DaaS Business Model", fontsize=18, fontweight="bold", pad=30)

    # Hide the y-axis ticks/labels entirely to abstract away the fake visual heights
    ax.set_yticks([])
    ax.set_ylim(0, 16000)
    plt.xticks(fontsize=14, fontweight="bold")

    # Clean up the spines
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    plt.tight_layout()
    output_path = os.path.join(output_dir, "Graph_6_Business_Model.png")
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    print("Generating Graph 6...")
    generate_business_model()
    print("Complete.")
