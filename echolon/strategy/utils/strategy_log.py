"""
Strategy Development Log Generator

Reads mode_decisions.json and generates a comprehensive STRATEGY_DEVELOPMENT_LOG.md
that provides LLM agents with:
- Performance metrics comparison across all versions
- Complete iteration history with exploration, validation, and exploitation outcomes
- Lessons learned from KEEP/REVERT decisions to guide future refinement

The log is designed to be easily parsed and understood by LLM agents for
strategy exploration and evaluation tasks.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import sys

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class StrategyDevelopmentLogGenerator:
    """
    Generates STRATEGY_DEVELOPMENT_LOG.md from mode_decisions.json.

    The log contains:
    - Chapter 1: Performance Metrics Table (all versions comparison)
    - Chapter 2: Iteration History (exploration → exploitation/validation cycles)

    Designed for LLM agent consumption to understand:
    - What strategies have been tried
    - What worked (KEEP) and what failed (REVERT)
    - Key learnings from each iteration
    """

    def __init__(self, strategy_bank_path: Optional[Path] = None):
        """
        Initialize the log generator.

        Args:
            strategy_bank_path: Path to strategy_bank directory (defaults to
                ``PathsConfig.output_dir`` derived from ``ECHOLON_PROJECT_ROOT``)
        """
        if strategy_bank_path is None:
            from echolon.config.paths_config import PathsConfig
            from echolon.config.settings import get_project_root
            self.strategy_bank_path = PathsConfig.from_project_root(get_project_root()).output_dir
        else:
            self.strategy_bank_path = Path(strategy_bank_path)
        self.mode_decisions_file = self.strategy_bank_path / "mode_decisions.json"
        self.log_file = self.strategy_bank_path / "STRATEGY_DEVELOPMENT_LOG.md"

    def generate_log(self) -> str:
        """
        Generate the complete strategy development log.

        Returns:
            str: Path to generated log file

        Raises:
            FileNotFoundError: If mode_decisions.json doesn't exist
        """
        if not self.mode_decisions_file.exists():
            raise FileNotFoundError(
                f"Mode decisions file not found: {self.mode_decisions_file}"
            )

        # Load mode decisions data
        with open(self.mode_decisions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Generate log content
        content = self._generate_header()
        content += self._generate_chapter1_metrics_table(data)
        content += self._generate_chapter2_iteration_history(data)

        # Write to file
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"✅ Strategy Development Log generated: {self.log_file}")
        return str(self.log_file)

    def _load_target_benchmarks(self) -> Dict[str, Any]:
        """Load target benchmarks from target.json dynamically."""
        target_path = self.strategy_bank_path / "target.json"
        defaults = {
            "sharpe_target": 1.2, "annual_return_target": 15.0,
            "max_drawdown_target": 15.0, "freq_min": 0.5, "freq_max": 1.5,
        }
        if not target_path.exists():
            return defaults
        with open(target_path, 'r', encoding='utf-8') as f:
            target = json.load(f)
        primary = target.get("primary_objective", {})
        secondary = target.get("secondary_objective", {})
        freq = secondary.get("average_trades_per_week", {})
        return {
            "sharpe_target": primary.get("sharpe_ratio", {}).get("target", defaults["sharpe_target"]),
            "annual_return_target": primary.get("annual_return_pct", {}).get("target", defaults["annual_return_target"]),
            "max_drawdown_target": target.get("hard_constraints", {}).get("max_drawdown_pct", {}).get("limit", defaults["max_drawdown_target"]),
            "freq_min": freq.get("target_min", defaults["freq_min"]),
            "freq_max": freq.get("freq_max", defaults["freq_max"]),
        }

    def _generate_header(self) -> str:
        """Generate log header with metadata and dynamic target benchmarks."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        t = self._load_target_benchmarks()
        self._target_benchmarks = t  # cache for use in status indicators

        return f"""# Strategy Development Log

> **Purpose**: This log provides a comprehensive history of strategy development iterations,
> including performance metrics, refinement decisions (KEEP/REVERT), and lessons learned.
> Use this to understand what has been tried, what worked, and what failed.

**Generated**: {now}
**Source**: `strategy_bank/mode_decisions.json`

---

## Target Benchmarks (Reference)

| Metric | Target | Hard Constraint |
|--------|--------|-----------------|
| Sharpe Ratio | ≥ {t['sharpe_target']} | - |
| Annual Return | ≥ {t['annual_return_target']}% | - |
| Max Drawdown | - | ≤ {t['max_drawdown_target']}% |
| Trading Frequency | {t['freq_min']}-{t['freq_max']}/week | - |

---

"""

    def _generate_chapter1_metrics_table(self, data: Dict[str, Any]) -> str:
        """
        Generate Chapter 1: Performance Metrics Table.

        Shows all versions in a comparison table for quick reference.
        """
        content = """## Chapter 1: Performance Metrics Comparison

This table shows performance metrics for all strategy versions.
Use this to quickly compare performance across iterations.

| Version | Mode | Parent | Sharpe | Annual Return | Max DD | Win Rate | Profit Factor | Trades | Trades/Week |
|---------|------|--------|--------|---------------|--------|----------|---------------|--------|-------------|
"""

        # Collect all versions across clusters
        all_versions: List[Tuple[str, Dict[str, Any]]] = []

        for _, cluster_data in sorted(data.items(), key=lambda x: int(x[0])):
            for version, entry in sorted(cluster_data.items(), key=lambda x: self._version_sort_key(x[0])):
                all_versions.append((version, entry))

        # Generate table rows
        for version, entry in all_versions:
            mode = entry.get("mode", "UNKNOWN")
            parent = entry.get("parent_version") or "-"
            metrics = entry.get("metrics_snapshot", {})

            sharpe = metrics.get("sharpe_ratio", 0)
            annual_return = metrics.get("annual_return", 0)
            max_dd = metrics.get("max_drawdown", 0)
            win_rate = metrics.get("win_rate", 0)
            profit_factor = metrics.get("profit_factor", 0)
            total_trades = metrics.get("total_trades", 0)
            trades_per_week = metrics.get("trades_per_week", 0)

            # Add status indicators
            sharpe_target = getattr(self, '_target_benchmarks', {}).get('sharpe_target', 1.2)
            sharpe_status = "✅" if sharpe >= sharpe_target else "⚠️" if sharpe >= sharpe_target * 0.6 else "❌"
            dd_status = "✅" if max_dd <= 0.15 else "❌"

            content += (
                f"| {version} | {mode} | {parent} | "
                f"{sharpe:.2f} {sharpe_status} | "
                f"{annual_return*100:.1f}% | "
                f"{max_dd*100:.1f}% {dd_status} | "
                f"{win_rate*100:.1f}% | "
                f"{profit_factor:.2f} | "
                f"{total_trades} | "
                f"{trades_per_week:.2f} |\n"
            )

        if not all_versions:
            content += "| - | - | - | - | - | - | - | - | - | - |\n"

        content += "\n---\n\n"
        return content

    def _generate_chapter2_iteration_history(self, data: Dict[str, Any]) -> str:
        """
        Generate Chapter 2: Iteration History.

        Organizes versions into iteration groups (cluster.base_version)
        showing the exploration version and all subsequent refinements.
        """
        content = """## Chapter 2: Iteration History

This chapter documents each strategy iteration's complete development cycle,
including the initial exploration, subsequent refinements, and outcomes.

**How to Read This Section**:
- Each iteration starts with an EXPLORATION version (e.g., 1.1, 2.1)
- EXPLOITATION versions test hypothesis to improve the strategy
- VALIDATION versions fix identified bugs
- Each refinement shows KEEP (successful) or REVERT (unsuccessful) decisions
- **Lessons Learned** sections highlight key insights from failures

"""

        # Process each cluster
        for cluster_id, cluster_data in sorted(data.items(), key=lambda x: int(x[0])):
            content += self._generate_cluster_section(cluster_id, cluster_data)

        return content

    def _generate_cluster_section(self, cluster_id: str, cluster_data: Dict[str, Any]) -> str:
        """Generate section for a single cluster (iteration group)."""

        content = f"### Cluster {cluster_id}\n\n"

        # Group versions by base version (e.g., 1.1, 1.2 are different base versions)
        # Validation versions like 1.11, 1.12 belong to base 1.1
        base_versions = self._group_by_base_version(cluster_data)

        for base_version, versions in sorted(base_versions.items(), key=lambda x: self._version_sort_key(x[0])):
            content += self._generate_base_version_section(base_version, versions, cluster_data)

        content += "---\n\n"
        return content

    def _group_by_base_version(self, cluster_data: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Group versions by their base version.

        e.g., 1.1, 1.11, 1.12 all belong to base 1.1
              1.2, 1.21, 1.22 all belong to base 1.2
        """
        groups: Dict[str, List[str]] = {}

        for version in cluster_data.keys():
            parts = version.split(".")
            if len(parts) >= 2:
                # Base version is cluster.minor (e.g., "1.1" from "1.11")
                cluster = parts[0]
                minor = parts[1]

                # Check if this is a validation version (e.g., "11" -> base "1")
                if len(minor) > 1 and minor[0] != '0':
                    base_minor = minor[0]
                    base_version = f"{cluster}.{base_minor}"
                else:
                    base_version = version

                if base_version not in groups:
                    groups[base_version] = []
                groups[base_version].append(version)

        # Sort versions within each group
        for base_ver in groups:
            groups[base_ver] = sorted(groups[base_ver], key=self._version_sort_key)

        return groups

    def _generate_base_version_section(
        self,
        base_version: str,
        versions: List[str],
        cluster_data: Dict[str, Any]
    ) -> str:
        """Generate section for a base version and its validation versions."""

        content = ""

        for version in versions:
            entry = cluster_data[version]
            mode = entry.get("mode", "UNKNOWN")

            if mode == "EXPLORATION":
                content += self._generate_exploration_section(version, entry)
            elif mode == "VALIDATION":
                content += self._generate_refinement_section(version, entry, "VALIDATION")
            elif mode == "EXPLOITATION":
                content += self._generate_refinement_section(version, entry, "EXPLOITATION")
            elif mode == "VALIDATION_EXPLOITATION":
                content += self._generate_refinement_section(version, entry, "VALIDATION_EXPLOITATION")

        return content

    def _generate_exploration_section(self, version: str, entry: Dict[str, Any]) -> str:
        """Generate section for an EXPLORATION version."""

        metrics = entry.get("metrics_snapshot", {})
        reflection = entry.get("strategy_reflection", "")

        # Load per-pathway data if available
        pathway_table = self._load_pathway_data(version)

        content = f"""#### Version {version} - EXPLORATION (Base Strategy)

**Performance Summary**:
- Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}
- Annual Return: {metrics.get('annual_return', 0)*100:.1f}%
- Max Drawdown: {metrics.get('max_drawdown', 0)*100:.1f}%
- Win Rate: {metrics.get('win_rate', 0)*100:.1f}%
- Profit Factor: {metrics.get('profit_factor', 0):.2f}
- Total Trades: {metrics.get('total_trades', 0)}
- Trades/Week: {metrics.get('trades_per_week', 0):.2f}

{pathway_table}**Strategy Analysis**:

{reflection if reflection else "_No analysis recorded._"}

"""
        return content

    def _generate_refinement_section(
        self,
        version: str,
        entry: Dict[str, Any],
        mode: str
    ) -> str:
        """Generate section for EXPLOITATION or VALIDATION versions."""

        metrics = entry.get("metrics_snapshot", {})
        reflection_data = entry.get("strategy_reflection", {})
        parent = entry.get("parent_version", "-")

        # Determine mode label and description
        if mode == "VALIDATION":
            mode_label = "VALIDATION"
            mode_description = "Bug Fixing"
        elif mode == "EXPLOITATION":
            mode_label = "EXPLOITATION"
            mode_description = "Hypothesis Testing"
        elif mode == "VALIDATION_EXPLOITATION":
            mode_label = "VALIDATION_EXPLOITATION"
            mode_description = "Bug Fixing + Hypothesis Testing"
        else:
            mode_label = mode
            mode_description = "Refinement"

        content = f"""#### Version {version} - {mode_label} ({mode_description})

**Parent Version**: {parent}

**Performance After Refinement**:
- Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}
- Annual Return: {metrics.get('annual_return', 0)*100:.1f}%
- Max Drawdown: {metrics.get('max_drawdown', 0)*100:.1f}%
- Total Trades: {metrics.get('total_trades', 0)}

"""

        # Process reflection entries
        if isinstance(reflection_data, dict) and reflection_data:
            content += "**Refinement Outcomes**:\n\n"

            keep_count = 0
            revert_count = 0

            for entry_num, entry_data in sorted(reflection_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                if isinstance(entry_data, dict):
                    decision = entry_data.get("decision", "UNKNOWN")
                    reflection = entry_data.get("reflection", "")
                else:
                    # Backward compatibility: string format
                    decision = "UNKNOWN"
                    reflection = entry_data

                # Count decisions
                if decision == "KEEP":
                    keep_count += 1
                    decision_icon = "✅"
                elif decision == "REVERT":
                    revert_count += 1
                    decision_icon = "❌"
                else:
                    decision_icon = "❓"

                content += f"**{entry_num}. {decision_icon} {decision}**\n\n"
                content += f"{reflection}\n\n"

                # Add structured failure metadata for REVERT decisions
                if decision == "REVERT" and isinstance(entry_data, dict):
                    params = entry_data.get("parameters_changed", [])
                    ranges = entry_data.get("value_ranges", {})
                    compound = entry_data.get("compound_change", None)
                    failure = entry_data.get("failure_mode", "")
                    if params or failure:
                        content += "  **Structured Failure Record:**\n"
                        if params:
                            content += f"  - Parameters changed: {', '.join(str(p) for p in params)}\n"
                        if ranges:
                            content += f"  - Value ranges: {ranges}\n"
                        if compound is not None:
                            content += f"  - Compound change: {'yes' if compound else 'no'}\n"
                        if failure:
                            content += f"  - Failure mode: {failure}\n"
                        content += "\n"

            # Summary
            content += f"**Summary**: {keep_count} KEEP, {revert_count} REVERT\n\n"

        elif isinstance(reflection_data, str) and reflection_data:
            content += f"**Notes**:\n\n{reflection_data}\n\n"

        return content



    def _load_pathway_data(self, version: str) -> str:
        """Load per-pathway data for a version from strategy JSON and entry_metrics.

        Reads pathway_summary from strategy JSON (Pydantic-validated, consistent format)
        and per-regime entry metrics from analysis reports.

        Returns formatted markdown table or empty string if data unavailable.
        """
        import glob as glob_module

        # Try to load pathway_summary from strategy JSON
        strategy_pattern = str(self.strategy_bank_path / version / "strategy" / "*_strategy.json")
        strategy_files = sorted(glob_module.glob(strategy_pattern))
        pathway_summary = None
        if strategy_files:
            try:
                with open(strategy_files[-1]) as f:  # Use latest strategy file
                    strategy_data = json.load(f)
                pathway_summary = (
                    strategy_data
                    .get("integrated_strategy", {})
                    .get("pathway_summary", None)
                )
            except (json.JSONDecodeError, KeyError):
                pass

        if not pathway_summary:
            return ""

        # Try to load per-regime entry metrics
        entry_metrics_path = (
            self.strategy_bank_path / version / "analysis" /
            "distributed_reports" / "entry_quality_package" / "entry_metrics.json"
        )
        regime_metrics = {}
        if entry_metrics_path.exists():
            try:
                with open(entry_metrics_path) as f:
                    metrics_data = json.load(f)
                regime_metrics = (
                    metrics_data
                    .get("segmentation_entry_quality", {})
                    .get("regime_metrics", {})
                )
            except (json.JSONDecodeError, KeyError):
                pass

        # Build table
        rows = []
        for pw in pathway_summary:
            regime = pw.get("regime", "?")
            direction = pw.get("direction", "?")
            indicator = pw.get("indicator", "?")
            rm = regime_metrics.get(regime, {})
            trades = rm.get("entries", "N/A")
            wr = f"{rm['win_rate_pct']:.1f}%" if "win_rate_pct" in rm else "N/A"
            avg_ret = f"{rm['avg_return_per_entry']:.0f}" if "avg_return_per_entry" in rm else "N/A"
            rows.append(f"| {regime} | {direction} | {indicator} | {trades} | {wr} | {avg_ret} |")

        if not rows:
            return ""

        table = "**Pathways:**\n"
        table += "| Regime | Dir | Indicator | Trades | WR% | Avg Return |\n"
        table += "|--------|-----|-----------|--------|-----|------------|\n"
        table += "\n".join(rows) + "\n\n"
        return table

    def _version_sort_key(self, version: str) -> List[int]:
        """
        Convert version string to sortable list of integers.

        Examples:
            "1.1" -> [1, 1]
            "1.11" -> [1, 1, 1]
            "2.21" -> [2, 2, 1]
        """
        parts = version.split(".")
        result = []

        for part in parts:
            if part.isdigit():
                result.append(int(part))
            else:
                # Split into individual digits for validation versions
                for char in part:
                    if char.isdigit():
                        result.append(int(char))

        return result


def generate_strategy_log(strategy_bank_path: Optional[str] = None) -> str:
    """
    Generate the strategy development log.

    Args:
        strategy_bank_path: Path to strategy_bank directory (optional)

    Returns:
        str: Path to generated log file

    Example:
        >>> log_path = generate_strategy_log()
        ✅ Strategy Development Log generated: .../strategy_bank/STRATEGY_DEVELOPMENT_LOG.md
    """
    path = Path(strategy_bank_path) if strategy_bank_path else None
    generator = StrategyDevelopmentLogGenerator(path)
    return generator.generate_log()


def get_strategy_log_content(strategy_bank_path: Optional[str] = None) -> str:
    """
    Generate and return the strategy development log content as a string.

    Useful for directly passing to LLM agents without file I/O.

    Args:
        strategy_bank_path: Path to strategy_bank directory (optional)

    Returns:
        str: Log content as markdown string
    """
    path = Path(strategy_bank_path) if strategy_bank_path else None
    generator = StrategyDevelopmentLogGenerator(path)

    if not generator.mode_decisions_file.exists():
        return "# Strategy Development Log\n\n_No mode decisions recorded yet._\n"

    with open(generator.mode_decisions_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    content = generator._generate_header()
    content += generator._generate_chapter1_metrics_table(data)
    content += generator._generate_chapter2_iteration_history(data)


    return content


# CLI support
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Strategy Development Log")
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to strategy_bank directory"
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print content to stdout instead of writing to file"
    )

    args = parser.parse_args()

    if args.print:
        content = get_strategy_log_content(args.path)
        print(content)
    else:
        log_path = generate_strategy_log(args.path)
        print(f"Log generated at: {log_path}")
