"""Message parsing utilities for agent mentions and routing."""

import re


class MessageParser:
    """Parser for extracting agent mentions and metadata from user messages."""

    def __init__(self, mention_prefix: str = "@"):
        """
        Initialize the message parser.

        Args:
            mention_prefix: Prefix character for agent mentions (default: "@")
        """
        self.mention_prefix = mention_prefix
        # Pattern to match @agent_name (alphanumeric, underscores, hyphens)
        self.mention_pattern = re.compile(rf"{re.escape(mention_prefix)}([a-zA-Z0-9_-]+)")

    def extract_mentions(self, message: str) -> list[str]:
        """
        Extract all agent mentions from a message.

        Args:
            message: User message text

        Returns:
            List of agent IDs mentioned in the message

        Example:
            >>> parser = MessageParser()
            >>> parser.extract_mentions("Hey @calculator_agent, what is 2+2?")
            ['calculator_agent']
            >>> parser.extract_mentions("@agent1 and @agent2, help me")
            ['agent1', 'agent2']
        """
        matches = self.mention_pattern.findall(message)
        # Return unique agent IDs in order of first appearance
        seen = set()
        unique_mentions = []
        for match in matches:
            if match not in seen:
                seen.add(match)
                unique_mentions.append(match)
        return unique_mentions

    def get_first_mention(self, message: str) -> str | None:
        """
        Get the first agent mention from a message.

        Args:
            message: User message text

        Returns:
            First mentioned agent ID, or None if no mentions found

        Example:
            >>> parser = MessageParser()
            >>> parser.get_first_mention("Hey @agent1, help")
            'agent1'
        """
        mentions = self.extract_mentions(message)
        return mentions[0] if mentions else None

    def remove_mentions(self, message: str) -> str:
        """
        Remove all agent mentions from a message.

        Args:
            message: User message text

        Returns:
            Message with mentions removed

        Example:
            >>> parser = MessageParser()
            >>> parser.remove_mentions("Hey @agent1, show me REQ123")
            'Hey , show me REQ123'
        """
        return self.mention_pattern.sub("", message).strip()

    def parse_message(self, message: str) -> dict[str, any]:
        """
        Parse a message and extract all relevant information.

        Args:
            message: User message text

        Returns:
            Dictionary with:
                - original_message: Original message text
                - mentions: List of agent IDs mentioned
                - clean_message: Message with mentions removed
                - has_mentions: Whether message contains mentions

        Example:
            >>> parser = MessageParser()
            >>> result = parser.parse_message("@agent1 help me with REQ123")
            >>> result['mentions']
            ['agent1']
            >>> result['clean_message']
            'help me with REQ123'
        """
        mentions = self.extract_mentions(message)
        clean_message = self.remove_mentions(message)

        return {
            "original_message": message,
            "mentions": mentions,
            "clean_message": clean_message,
            "has_mentions": len(mentions) > 0,
            "first_mention": mentions[0] if mentions else None,
        }

    def validate_mentions(
        self, message: str, available_agents: list[str], allow_multiple: bool = False
    ) -> tuple[bool, str | None]:
        """
        Validate that mentions in the message are valid.

        Args:
            message: User message text
            available_agents: List of valid agent IDs
            allow_multiple: Whether multiple mentions are allowed

        Returns:
            Tuple of (is_valid, error_message)

        Example:
            >>> parser = MessageParser()
            >>> parser.validate_mentions("@agent1 help", ['agent1', 'agent2'])
            (True, None)
            >>> parser.validate_mentions("@unknown help", ['agent1'])
            (False, "Unknown agent mentioned: unknown")
        """
        mentions = self.extract_mentions(message)

        # Check if multiple mentions when not allowed
        if not allow_multiple and len(mentions) > 1:
            return False, f"Only one agent mention allowed, found: {', '.join(mentions)}"

        # Check if all mentions are valid agents
        invalid_mentions = [m for m in mentions if m not in available_agents]
        if invalid_mentions:
            return False, f"Unknown agent(s) mentioned: {', '.join(invalid_mentions)}"

        return True, None


# Global parser instance
default_parser = MessageParser()


def extract_agent_mention(message: str, available_agents: list[str]) -> str | None:
    """
    Convenience function to extract the first valid agent mention.

    Args:
        message: User message text
        available_agents: List of valid agent IDs

    Returns:
        First valid agent ID mentioned, or None
    """
    mention = default_parser.get_first_mention(message)
    if mention and mention in available_agents:
        return mention
    return None
