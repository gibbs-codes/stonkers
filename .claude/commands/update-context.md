# Update Context

Update the `.claude/CLAUDE.md` context file to reflect the current state of the stonkers codebase.

## Instructions

1. **Explore the current codebase state** using the Explore agent to gather:
   - Current project structure (any new directories or files)
   - Enabled/disabled strategies and their current backtest performance
   - Current risk management settings from `config.yaml`
   - Any new strategies added
   - Changes to the trading engine or key components
   - Current trading pairs and timeframes
   - Any new analysis tools or utilities
   - Changes to the database schema
   - Updates to dependencies

2. **Compare with existing context** by reading `.claude/CLAUDE.md` to identify:
   - What has changed since last refresh
   - What is outdated or incorrect
   - What new sections need to be added

3. **Update the CLAUDE.md file** with:
   - Current accurate information
   - Any new strategies with their performance metrics
   - Updated risk settings if changed
   - New commands or utilities
   - Corrected file references
   - Updated architecture notes if structure changed

4. **Summarize the drift** - Tell the user what changed between the old and new context so they understand what evolved.

## Output Format

After updating, provide a brief summary:
- **Added**: New items discovered
- **Updated**: Items that changed
- **Removed**: Items no longer present

Keep the same general structure of CLAUDE.md but update all content to be accurate.
