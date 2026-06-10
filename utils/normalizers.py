"""
Utility module for data normalization in FloripaScraper.

This module provides functions to normalize and validate various Brazilian
data formats including CNPJ, CPF, CEP, phone numbers, dates, and currency.
"""

import logging
import re
from datetime import datetime
from typing import Optional

# Configure module logger
logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """Custom exception raised when data normalization fails."""
    pass


def normalize_cnpj(cnpj: str) -> str:
    """
    Normalize and validate a CNPJ (Brazilian company tax ID).

    Removes all punctuation, validates that it contains exactly 14 digits,
    and returns the raw digits.

    Args:
        cnpj: A string representing a CNPJ. Can contain punctuation and
              formatting (e.g., "12.345.678/0001-90").

    Returns:
        A string containing only the 14 digits of the CNPJ.

    Raises:
        NormalizationError: If the CNPJ is invalid (not 14 digits, empty,
                          or contains non-numeric characters after cleaning).

    Example:
        >>> normalize_cnpj("12.345.678/0001-90")
        '12345678000190'
    """
    if cnpj is None:
        logger.warning("normalize_cnpj received None, returning empty string")
        return ""

    cnpj_str = str(cnpj).strip()

    if not cnpj_str:
        logger.debug("normalize_cnpj received empty string, returning empty")
        return ""

    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', cnpj_str)

    if not digits_only:
        logger.warning(f"normalize_cnpj: No digits found in input '{cnpj}', returning empty")
        return ""

    if len(digits_only) != 14:
        logger.error(f"normalize_cnpj: Invalid CNPJ length {len(digits_only)} (expected 14) for '{cnpj}'")
        raise NormalizationError(
            f"Invalid CNPJ: must contain exactly 14 digits, got {len(digits_only)}"
        )

    logger.debug(f"normalize_cnpj: Successfully normalized '{cnpj}' to '{digits_only}'")
    return digits_only


def normalize_cpf(cpf: str) -> str:
    """
    Normalize and validate a CPF (Brazilian individual tax ID).

    Removes all punctuation, validates that it contains exactly 11 digits,
    and returns the raw digits.

    Args:
        cpf: A string representing a CPF. Can contain punctuation and
             formatting (e.g., "123.456.789-00").

    Returns:
        A string containing only the 11 digits of the CPF.

    Raises:
        NormalizationError: If the CPF is invalid (not 11 digits, empty,
                          or contains non-numeric characters after cleaning).

    Example:
        >>> normalize_cpf("123.456.789-00")
        '12345678900'
    """
    if cpf is None:
        logger.warning("normalize_cpf received None, returning empty string")
        return ""

    cpf_str = str(cpf).strip()

    if not cpf_str:
        logger.debug("normalize_cpf received empty string, returning empty")
        return ""

    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', cpf_str)

    if not digits_only:
        logger.warning(f"normalize_cpf: No digits found in input '{cpf}', returning empty")
        return ""

    if len(digits_only) != 11:
        logger.error(f"normalize_cpf: Invalid CPF length {len(digits_only)} (expected 11) for '{cpf}'")
        raise NormalizationError(
            f"Invalid CPF: must contain exactly 11 digits, got {len(digits_only)}"
        )

    logger.debug(f"normalize_cpf: Successfully normalized '{cpf}' to '{digits_only}'")
    return digits_only


def normalize_cep(cep: str) -> str:
    """
    Normalize a CEP (Brazilian postal code) to standard format.

    Removes all non-digit characters and formats the result as XXXXX-XXX.

    Args:
        cep: A string representing a CEP. Can contain punctuation and
             formatting (e.g., "88020-300" or "88020300").

    Returns:
        A string formatted as 'XXXXX-XXX' (8 digits with hyphen).

    Raises:
        NormalizationError: If the CEP does not contain exactly 8 digits.

    Example:
        >>> normalize_cep("88020-300")
        '88020-300'
    """
    if cep is None:
        logger.warning("normalize_cep received None, returning empty string")
        return ""

    cep_str = str(cep).strip()

    if not cep_str:
        logger.debug("normalize_cep received empty string, returning empty")
        return ""

    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', cep_str)

    if not digits_only:
        logger.warning(f"normalize_cep: No digits found in input '{cep}', returning empty")
        return ""

    if len(digits_only) != 8:
        logger.error(f"normalize_cep: Invalid CEP length {len(digits_only)} (expected 8) for '{cep}'")
        raise NormalizationError(
            f"Invalid CEP: must contain exactly 8 digits, got {len(digits_only)}"
        )

    formatted = f"{digits_only[:5]}-{digits_only[5:]}"
    logger.debug(f"normalize_cep: Successfully normalized '{cep}' to '{formatted}'")
    return formatted


def normalize_data(
    data: str,
    formato_origem: str = "%d/%m/%Y"
) -> str:
    """
    Convert a date string to ISO 8601 format (YYYY-MM-DD).

    Parses the input date using the specified source format and returns
    it in ISO 8601 format.

    Args:
        data: A string representing a date.
        formato_origem: The format of the input date string.
                        Default is "%d/%m/%Y" (DD/MM/YYYY).

    Returns:
        A string formatted as 'YYYY-MM-DD' (ISO 8601).

    Raises:
        NormalizationError: If the date string cannot be parsed with
                          the specified format.

    Example:
        >>> normalize_data("10/06/2024")
        '2024-06-10'
        >>> normalize_data("2024-06-10", "%Y-%m-%d")
        '2024-06-10'
    """
    if data is None:
        logger.warning("normalize_data received None, returning empty string")
        return ""

    data_str = str(data).strip()

    if not data_str:
        logger.debug("normalize_data received empty string, returning empty")
        return ""

    try:
        parsed_date = datetime.strptime(data_str, formato_origem)
        iso_date = parsed_date.strftime("%Y-%m-%d")
        logger.debug(f"normalize_data: Successfully converted '{data_str}' to '{iso_date}'")
        return iso_date
    except ValueError as e:
        logger.error(f"normalize_data: Failed to parse '{data_str}' with format '{formato_origem}': {e}")
        raise NormalizationError(
            f"Invalid date format: cannot parse '{data_str}' using format '{formato_origem}'"
        ) from e


def normalize_telefone(tel: str) -> str:
    """
    Normalize a phone number to Brazilian format with country code.

    Removes all non-digit characters and formats the result as
    +55 48 XXXXX-XXXX (for Santa Catarina region).

    Args:
        tel: A string representing a phone number. Can contain various
             formats including country code, area code, and separators.

    Returns:
        A string formatted as '+55 48 XXXXX-XXXX' or '+55 XX XXXXX-XXXX'
        for other area codes.

    Raises:
        NormalizationError: If the phone number does not contain
                          10 or 11 digits (without country code).

    Example:
        >>> normalize_telefone("(48) 99999-1234")
        '+55 48 99999-1234'
        >>> normalize_telefone("48999991234")
        '+55 48 99999-1234'
    """
    if tel is None:
        logger.warning("normalize_telefone received None, returning empty string")
        return ""

    tel_str = str(tel).strip()

    if not tel_str:
        logger.debug("normalize_telefone received empty string, returning empty")
        return ""

    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', tel_str)

    if not digits_only:
        logger.warning(f"normalize_telefone: No digits found in input '{tel}', returning empty")
        return ""

    # Handle numbers that already include country code (55)
    if digits_only.startswith('55') and len(digits_only) > 10:
        # Remove country code for processing
        digits_only = digits_only[2:]

    if len(digits_only) == 10:
        # 10 digits: DD DDDD-DDDD (landline or mobile without 9)
        area_code = digits_only[:2]
        number = digits_only[2:]
        formatted = f"+55 {area_code} {number[:5]}-{number[5:]}"
    elif len(digits_only) == 11:
        # 11 digits: 9 DDDD-DDDD with area code
        area_code = digits_only[:2]
        number = digits_only[2:]
        formatted = f"+55 {area_code} {number[:5]}-{number[5:]}"
    else:
        logger.error(f"normalize_telefone: Invalid phone length {len(digits_only)} for '{tel}'")
        raise NormalizationError(
            f"Invalid phone number: must contain 10 or 11 digits, got {len(digits_only)}"
        )

    logger.debug(f"normalize_telefone: Successfully normalized '{tel}' to '{formatted}'")
    return formatted


def normalize_moeda(valor: str) -> float:
    """
    Convert a Brazilian Real currency string to a float.

    Handles various currency formats including the R$ symbol,
    thousands separators (period), and decimal separators (comma).

    Args:
        valor: A string representing a monetary value in Brazilian Real.
               Can include R$ symbol, period as thousands separator,
               and comma as decimal separator.

    Returns:
        A float representing the monetary value.

    Raises:
        NormalizationError: If the value cannot be parsed as a valid
                          monetary amount.

    Example:
        >>> normalize_moeda("R$ 1.234,56")
        1234.56
        >>> normalize_moeda("1.234,56")
        1234.56
    """
    if valor is None:
        logger.warning("normalize_moeda received None, returning 0.0")
        return 0.0

    valor_str = str(valor).strip()

    if not valor_str:
        logger.debug("normalize_moeda received empty string, returning 0.0")
        return 0.0

    try:
        # Remove R$ symbol and any other non-numeric characters except comma and period
        cleaned = re.sub(r'[R$\s]', '', valor_str)

        if not cleaned:
            logger.warning(f"normalize_moeda: No numeric content found in '{valor}', returning 0.0")
            return 0.0

        # Handle Brazilian format: period as thousands separator, comma as decimal
        # First, remove all periods (thousands separators)
        cleaned = cleaned.replace('.', '')

        # Then replace comma with period (decimal separator)
        cleaned = cleaned.replace(',', '.')

        # Convert to float
        result = float(cleaned)
        logger.debug(f"normalize_moeda: Successfully converted '{valor}' to {result}")
        return result

    except ValueError as e:
        logger.error(f"normalize_moeda: Failed to parse '{valor}': {e}")
        raise NormalizationError(
            f"Invalid monetary value: cannot parse '{valor}'"
        ) from e


def normalize_preco(valor: str) -> float:
    """
    Convert a price string to a float (simplified version without currency symbol).

    Handles various price formats without the R$ symbol, using period
    as thousands separator and comma as decimal separator.

    Args:
        valor: A string representing a price. Can include period as
               thousands separator and comma as decimal separator.

    Returns:
        A float representing the price value.

    Raises:
        NormalizationError: If the value cannot be parsed as a valid number.

    Example:
        >>> normalize_preco("1.234,56")
        1234.56
        >>> normalize_preco("1234.56")
        1234.56
    """
    if valor is None:
        logger.warning("normalize_preco received None, returning 0.0")
        return 0.0

    valor_str = str(valor).strip()

    if not valor_str:
        logger.debug("normalize_preco received empty string, returning 0.0")
        return 0.0

    try:
        # Remove any whitespace
        cleaned = valor_str.strip()

        if not cleaned:
            logger.warning(f"normalize_preco: Empty input after stripping, returning 0.0")
            return 0.0

        # Handle Brazilian format: period as thousands separator, comma as decimal
        # First, remove all periods (thousands separators)
        cleaned = cleaned.replace('.', '')

        # Then replace comma with period (decimal separator)
        cleaned = cleaned.replace(',', '.')

        # Convert to float
        result = float(cleaned)
        logger.debug(f"normalize_preco: Successfully converted '{valor}' to {result}")
        return result

    except ValueError as e:
        logger.error(f"normalize_preco: Failed to parse '{valor}': {e}")
        raise NormalizationError(
            f"Invalid price value: cannot parse '{valor}'"
        ) from e