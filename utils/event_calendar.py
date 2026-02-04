"""
Event Calendar Management

Tools for managing the economic calendar and market events:
- Load events from configuration
- Schedule recurring events (FOMC meetings, etc.)
- Import from external calendars
- Manual event entry

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import yaml
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

from agents.risk.event_guard import EventGuard, EventType, EventImpact


class EventCalendar:
    """
    Manages economic calendar and market events.

    Features:
    - Load events from YAML configuration
    - Add/remove events programmatically
    - Schedule recurring events
    - Import from external sources
    """

    def __init__(
        self,
        event_guard: EventGuard,
        config_path: Optional[str] = None,
        logger=None,
    ):
        """
        Initialize event calendar.

        Args:
            event_guard: EventGuard instance
            config_path: Path to events configuration file
            logger: Logger instance
        """
        self.event_guard = event_guard
        self.logger = logger or logging.getLogger(__name__)

        # Default config path
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "events_config.yaml"
            )

        self.config_path = config_path

    def load_from_config(self) -> int:
        """
        Load events from YAML configuration file.

        Returns:
            Number of events loaded
        """
        if not os.path.exists(self.config_path):
            self.logger.warning(f"Events config not found: {self.config_path}")
            return 0

        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)

            if not config or 'events' not in config:
                self.logger.warning("No events found in config")
                return 0

            events = config['events']
            count = 0

            for event_data in events:
                try:
                    # Parse event type
                    event_type = EventType[event_data['type'].upper()]

                    # Parse impact level
                    impact = EventImpact[event_data.get('impact', 'HIGH').upper()]

                    # Parse timestamp
                    timestamp_str = event_data['timestamp']
                    if isinstance(timestamp_str, str):
                        # Parse datetime string
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        timestamp = dt.timestamp()
                    else:
                        timestamp = float(timestamp_str)

                    # Get description
                    description = event_data.get('description', event_type.value)

                    # Get symbols (for symbol-specific events)
                    symbols = event_data.get('symbols', None)
                    if symbols and isinstance(symbols, str):
                        symbols = [s.strip() for s in symbols.split(',')]

                    # Add event
                    event_id = self.event_guard.add_event(
                        event_type=event_type,
                        timestamp=timestamp,
                        description=description,
                        impact=impact,
                        symbols=symbols,
                    )

                    # Add symbol allowlist if specified
                    if 'allowlist' in event_data:
                        allowlist = event_data['allowlist']
                        if isinstance(allowlist, str):
                            allowlist = [s.strip() for s in allowlist.split(',')]
                        self.event_guard.add_symbol_to_allowlist(event_id, allowlist)

                    count += 1

                except Exception as e:
                    self.logger.error(f"Error loading event: {event_data} - {e}")
                    continue

            self.logger.info(f"Loaded {count} events from config")
            return count

        except Exception as e:
            self.logger.error(f"Error loading events config: {e}")
            return 0

    def add_fomc_meetings(self, year: int) -> int:
        """
        Add FOMC meetings for a given year.

        FOMC typically meets 8 times per year.
        This is a template - update with actual dates.

        Args:
            year: Year to add meetings

        Returns:
            Number of meetings added
        """
        # FOMC meeting dates for 2025 (example - update with actual dates)
        fomc_dates_2025 = [
            "2025-01-28 14:00:00",  # January
            "2025-03-18 14:00:00",  # March
            "2025-05-06 14:00:00",  # May
            "2025-06-17 14:00:00",  # June
            "2025-07-29 14:00:00",  # July
            "2025-09-16 14:00:00",  # September
            "2025-11-04 14:00:00",  # November
            "2025-12-16 14:00:00",  # December
        ]

        if year != 2025:
            self.logger.warning(f"FOMC dates not configured for {year}")
            return 0

        count = 0
        for date_str in fomc_dates_2025:
            try:
                dt = datetime.fromisoformat(date_str)
                timestamp = dt.timestamp()

                self.event_guard.add_event(
                    event_type=EventType.FOMC,
                    timestamp=timestamp,
                    description=f"FOMC Meeting - {dt.strftime('%B %Y')}",
                    impact=EventImpact.HIGH,
                )
                count += 1

            except Exception as e:
                self.logger.error(f"Error adding FOMC meeting: {date_str} - {e}")

        self.logger.info(f"Added {count} FOMC meetings for {year}")
        return count

    def add_nfp_releases(self, year: int, month: int = None) -> int:
        """
        Add Non-Farm Payroll releases.

        NFP is released first Friday of each month at 8:30 AM ET.

        Args:
            year: Year
            month: Specific month (default: all months)

        Returns:
            Number of NFP releases added
        """
        count = 0

        months = [month] if month else range(1, 13)

        for m in months:
            try:
                # Find first Friday of month
                first_day = datetime(year, m, 1)

                # Find first Friday
                days_ahead = (4 - first_day.weekday()) % 7  # Friday is 4
                if days_ahead == 0:
                    days_ahead = 7  # If first day is Friday, go to next week
                first_friday = first_day + timedelta(days=days_ahead)

                # Set time to 8:30 AM ET (13:30 UTC)
                nfp_time = first_friday.replace(hour=13, minute=30, second=0)
                timestamp = nfp_time.timestamp()

                # Only add future events
                if timestamp > time.time():
                    self.event_guard.add_event(
                        event_type=EventType.NFP,
                        timestamp=timestamp,
                        description=f"Non-Farm Payroll - {nfp_time.strftime('%B %Y')}",
                        impact=EventImpact.HIGH,
                    )
                    count += 1

            except Exception as e:
                self.logger.error(f"Error adding NFP for {year}-{m:02d}: {e}")

        self.logger.info(f"Added {count} NFP releases for {year}")
        return count

    def add_cpi_releases(self, year: int, month: int = None) -> int:
        """
        Add CPI report releases.

        CPI is typically released mid-month.

        Args:
            year: Year
            month: Specific month (default: all months)

        Returns:
            Number of CPI releases added
        """
        # CPI release dates for 2025 (example - update with actual dates)
        cpi_dates_2025 = [
            "2025-01-15 08:30:00",
            "2025-02-12 08:30:00",
            "2025-03-12 08:30:00",
            "2025-04-10 08:30:00",
            "2025-05-14 08:30:00",
            "2025-06-11 08:30:00",
            "2025-07-10 08:30:00",
            "2025-08-13 08:30:00",
            "2025-09-10 08:30:00",
            "2025-10-15 08:30:00",
            "2025-11-13 08:30:00",
            "2025-12-10 08:30:00",
        ]

        if year != 2025:
            self.logger.warning(f"CPI dates not configured for {year}")
            return 0

        count = 0
        for date_str in cpi_dates_2025:
            try:
                dt = datetime.fromisoformat(date_str)

                # Filter by month if specified
                if month and dt.month != month:
                    continue

                timestamp = dt.timestamp()

                # Only add future events
                if timestamp > time.time():
                    self.event_guard.add_event(
                        event_type=EventType.CPI,
                        timestamp=timestamp,
                        description=f"CPI Report - {dt.strftime('%B %Y')}",
                        impact=EventImpact.HIGH,
                    )
                    count += 1

            except Exception as e:
                self.logger.error(f"Error adding CPI: {date_str} - {e}")

        self.logger.info(f"Added {count} CPI releases for {year}")
        return count

    def add_exchange_listing(
        self,
        symbol: str,
        exchange: str,
        listing_time: datetime,
        allow_trading: bool = True,
    ) -> str:
        """
        Add exchange listing event.

        Args:
            symbol: Trading symbol
            exchange: Exchange name
            listing_time: Listing datetime
            allow_trading: Add symbol to allowlist (default: True)

        Returns:
            Event ID
        """
        timestamp = listing_time.timestamp()

        event_id = self.event_guard.add_event(
            event_type=EventType.EXCHANGE_LISTING,
            timestamp=timestamp,
            description=f"{symbol} listing on {exchange}",
            impact=EventImpact.SYMBOL_SPECIFIC,
            symbols=[symbol],
        )

        # Add to allowlist if requested
        if allow_trading:
            self.event_guard.add_symbol_to_allowlist(event_id, [symbol])
            self.logger.info(f"Added {symbol} to allowlist for listing event")

        return event_id

    def add_custom_event(
        self,
        description: str,
        event_time: datetime,
        impact: EventImpact = EventImpact.HIGH,
        symbols: Optional[List[str]] = None,
    ) -> str:
        """
        Add custom event.

        Args:
            description: Event description
            event_time: Event datetime
            impact: Impact level
            symbols: Symbol-specific (optional)

        Returns:
            Event ID
        """
        timestamp = event_time.timestamp()

        event_id = self.event_guard.add_event(
            event_type=EventType.CUSTOM,
            timestamp=timestamp,
            description=description,
            impact=impact,
            symbols=symbols,
        )

        self.logger.info(f"Added custom event: {description} at {event_time}")
        return event_id

    def get_calendar_summary(self, days: int = 7) -> Dict:
        """
        Get summary of upcoming events.

        Args:
            days: Days to look ahead

        Returns:
            Calendar summary
        """
        upcoming = self.event_guard.get_upcoming_events(hours=days * 24)

        summary = {
            "total_upcoming": len(upcoming),
            "events_by_type": {},
            "events_by_day": {},
            "high_impact_count": 0,
        }

        for event in upcoming:
            # Count by type
            event_type = event.event_type.value
            summary["events_by_type"][event_type] = summary["events_by_type"].get(event_type, 0) + 1

            # Count by day
            event_date = datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d")
            if event_date not in summary["events_by_day"]:
                summary["events_by_day"][event_date] = []
            summary["events_by_day"][event_date].append({
                "type": event.event_type.value,
                "time": datetime.fromtimestamp(event.timestamp).strftime("%H:%M"),
                "description": event.description,
            })

            # Count high impact
            if event.impact == EventImpact.HIGH:
                summary["high_impact_count"] += 1

        return summary


def create_event_calendar(
    event_guard,
    config_path: Optional[str] = None,
    logger=None,
) -> EventCalendar:
    """
    Create and configure event calendar.

    Args:
        event_guard: EventGuard instance
        config_path: Path to events config
        logger: Logger instance

    Returns:
        EventCalendar instance
    """
    return EventCalendar(
        event_guard=event_guard,
        config_path=config_path,
        logger=logger,
    )
