from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser

def get_parser(report_type: str):
    """
    Factory function to return the appropriate parser instance 
    based on the given report type.
    """
    if report_type == "TYPE_A":
        return TypeAParser()
    elif report_type == "TYPE_B":
        return TypeBParser()
    raise ValueError(f"Unknown report type: {report_type}")