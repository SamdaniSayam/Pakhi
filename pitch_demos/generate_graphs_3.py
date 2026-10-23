import matplotlib.pyplot as plt
import os

# Set a nice style for pitch deck graphics
plt.style.use("seaborn-v0_8-darkgrid")

# Ensure output directory exists
output_dir = "/home/megalith/Desktop/pakhi/pitch_demos"
os.makedirs(output_dir, exist_ok=True)


def generate_tam_sam_som():
    fig, ax = plt.subplots(figsize=(10, 7))

    # We use non-linear widths to ensure the text fits inside a nice funnel shape.
    # Strict proportionality makes SOM an invisible sliver.
    widths = [1.0, 0.65, 0.35]
    y_positions = [3, 2, 1]
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e"]

    labels = [
        "TAM (Total Available Market) - $25 Billion\nGlobal climate risk transfer & weather derivatives ecosystem",
        "SAM (Serviceable Available Market) - $4.6 Billion\nActive, traded weather derivatives and analytics market",
        "SOM (Serviceable Obtainable Market) - $20M to $50M\nTargeted boutique agricultural & energy trading desks",
    ]

    for i in range(3):
        # Draw horizontal bar centered at 0 to create a funnel layer
        ax.barh(
            y_positions[i],
            widths[i],
            height=0.9,
            left=-widths[i] / 2,
            color=colors[i],
            align="center",
            edgecolor="white",
            linewidth=2,
        )

        # Add the explanatory text inside the funnel block
        ax.text(
            0,
            y_positions[i],
            labels[i],
            ha="center",
            va="center",
            color="white",
            fontsize=13,
            fontweight="bold",
            bbox=dict(facecolor="black", alpha=0.3, edgecolor="none", boxstyle="round,pad=0.5"),
        )

    # Remove all axes lines and ticks for a clean infographic look
    ax.axis("off")
    ax.set_ylim(0.2, 3.8)

    # Add Title
    ax.set_title("Graph 5: Market Opportunity Sizing", fontsize=18, fontweight="bold", pad=20)

    plt.tight_layout()
    output_path = os.path.join(output_dir, "Graph_5_TAM_SAM_SOM.png")
    plt.savefig(output_path, dpi=300, bbox_inches="tight", transparent=False, facecolor="white")
    plt.close()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    print("Generating Graph 5...")
    generate_tam_sam_som()
    print("Complete.")
