# utils.py
import pandas as pd
import re
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def convert_excel_formula_to_pandas(formula):
    """
    Attempt to convert an Excel formula to a pandas equivalent
    
    Args:
        formula (str): Excel formula string
        
    Returns:
        str: Pandas equivalent code or explanation
    """
    formula = formula.strip()
    
    # Handle VLOOKUP
    vlookup_pattern = r'VLOOKUP\((.*?),(.*?),(.*?),.*?\)'
    vlookup_match = re.search(vlookup_pattern, formula, re.IGNORECASE)
    if vlookup_match:
        lookup_value = vlookup_match.group(1)
        table_array = vlookup_match.group(2)
        col_index = vlookup_match.group(3)
        return f"# Equivalent to: {formula}\n" + \
               f"df.loc[df['key_column'] == {lookup_value}, df.columns[{col_index}-1]].values[0]"
    
    # Handle SUM
    sum_pattern = r'SUM\((.*?)\)'
    sum_match = re.search(sum_pattern, formula, re.IGNORECASE)
    if sum_match:
        range_str = sum_match.group(1)
        return f"# Equivalent to: {formula}\n" + \
               f"df[relevant_columns].sum()"
    
    # Handle SUMIFS, a more complex function
    sumifs_pattern = r'SUMIFS\((.*?),(.*?)\)'
    sumifs_match = re.search(sumifs_pattern, formula, re.IGNORECASE)
    if sumifs_match:
        return f"# Equivalent to: {formula}\n" + \
               f"df[df['condition_column'] == condition_value]['sum_column'].sum()"
    
    # Handle IF
    if_pattern = r'IF\((.*?),(.*?),(.*?)\)'
    if_match = re.search(if_pattern, formula, re.IGNORECASE)
    if if_match:
        condition = if_match.group(1)
        true_val = if_match.group(2)
        false_val = if_match.group(3)
        return f"# Equivalent to: {formula}\n" + \
               f"np.where({condition}, {true_val}, {false_val})"
    
    # Default case
    return f"# No direct pandas equivalent found for: {formula}\n" + \
           f"# Will need custom implementation"

def extract_data_sources_from_vba(vba_code):
    """
    Extract potential data sources from VBA code
    
    Args:
        vba_code (str): VBA code string
        
    Returns:
        list: List of potential data sources
    """
    data_sources = []
    
    # Look for database connections
    connection_patterns = [
        r'(?:Provider=([^;]+))',
        r'(?:Data Source=([^;]+))',
        r'(?:Server=([^;]+))',
        r'(?:Database=([^;]+))',
        r'(?:DSN=([^;]+))'
    ]
    
    for pattern in connection_patterns:
        matches = re.findall(pattern, vba_code, re.IGNORECASE)
        data_sources.extend(matches)
    
    # Look for file access
    file_patterns = [
        r'Open\s+"([^"]+)"',
        r'Workbooks.Open\s*\("([^"]+)"\)',
        r'GetOpenFilename\s*\("([^"]+)"'
    ]
    
    for pattern in file_patterns:
        matches = re.findall(pattern, vba_code, re.IGNORECASE)
        data_sources.extend(matches)
    
    return list(set(data_sources))  # Remove duplicates

def estimate_remediation_difficulty(analysis):
    """
    Estimate the difficulty of remediating an EUDA based on its analysis
    
    Args:
        analysis (dict): EUDA analysis dictionary
        
    Returns:
        tuple: (difficulty_score, difficulty_rating, reasons)
    """
    score = 0
    reasons = []
    
    # Base on complexity
    complexity_score = analysis.get('complexity_score', 50)
    score += complexity_score * 0.5  # 50% weight from complexity
    
    # VBA complexity
    vba_module_count = analysis.get('vba_module_count', 0)
    if vba_module_count > 0:
        score += min(vba_module_count * 5, 20)
        reasons.append(f"Contains {vba_module_count} VBA modules")
    
    # Data connections
    connection_count = analysis.get('connection_count', 0)
    if connection_count > 0:
        score += min(connection_count * 5, 15)
        reasons.append(f"Has {connection_count} external data connections")
    
    # Advanced Excel functions
    advanced_function_count = 0
    for formula in analysis.get('formulas', []):
        formula_text = formula.get('formula', '').lower()
        if any(func in formula_text for func in ['vlookup', 'index', 'match', 'indirect', 'offset']):
            advanced_function_count += 1
    
    if advanced_function_count > 0:
        score += min(advanced_function_count, 15)
        reasons.append(f"Uses {advanced_function_count} advanced Excel functions")
    
    # Determine rating
    if score < 30:
        rating = "Easy"
    elif score < 60:
        rating = "Moderate"
    elif score < 80:
        rating = "Difficult"
    else:
        rating = "Very Difficult"
    
    return (score, rating, reasons)

def create_data_model_recommendation(analysis):
    """
    Create a recommendation for a data model based on EUDA analysis
    
    Args:
        analysis (dict): EUDA analysis dictionary
        
    Returns:
        dict: Data model recommendation
    """
    sheets = analysis.get('sheet_names', [])
    
    # Extract potential entities from sheet names
    entities = []
    for sheet in sheets:
        # Common suffixes that indicate data sheets
        if any(suffix in sheet.lower() for suffix in ['data', 'table', 'list', 'master', 'info']):
            entities.append({
                'name': sheet.replace('Data', '').replace('Table', '').replace('List', '').strip(),
                'source': f"Sheet: {sheet}"
            })
    
    # Look for relationships in formulas
    relationships = []
    for formula in analysis.get('formulas', [])[:50]:  # Limit to first 50 formulas
        formula_text = formula.get('formula', '').lower()
        if 'vlookup' in formula_text or 'index' in formula_text and 'match' in formula_text:
            # This indicates a potential relationship
            source_sheet = formula.get('sheet', '')
            if source_sheet and any(entity['source'].endswith(source_sheet) for entity in entities):
                # Find which other sheet this formula might be referencing
                for sheet in sheets:
                    if sheet != source_sheet and sheet in formula_text:
                        relationships.append({
                            'from': source_sheet,
                            'to': sheet,
                            'type': 'lookup'
                        })
    
    return {
        'entities': entities,
        'relationships': relationships,
        'recommendation': "Based on the EUDA analysis, consider creating a normalized data model with the entities listed above. Use SQLAlchemy ORM to model these entities and their relationships in Python."
    }
