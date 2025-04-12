# main.py
import os
import sys
import logging
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QWidget, QScrollArea, QMessageBox
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import pandas as pd
import numpy as np
import win32com.client
import pythoncom
import psycopg2
from psycopg2.extras import execute_values
import json
import re
import anthropic
import boto3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ExcelAnalyzer:
    """Class to analyze Excel files and extract information about formulas, macros, and data connections."""
    
    def __init__(self):
        self.excel_app = None

    def initialize_excel(self):
        """Initialize Excel COM object"""
        pythoncom.CoInitialize()
        self.excel_app = win32com.client.Dispatch("Excel.Application")
        self.excel_app.Visible = False
        self.excel_app.DisplayAlerts = False
        return self.excel_app

    def close_excel(self):
        """Close Excel COM object"""
        if self.excel_app:
            self.excel_app.Quit()
            self.excel_app = None
        pythoncom.CoUninitialize()

    def analyze_excel_file(self, file_path):
        """Analyze Excel file and return information about its contents"""
        try:
            # Initialize Excel if not already done
            if not self.excel_app:
                self.initialize_excel()
            
            # Open workbook
            workbook = self.excel_app.Workbooks.Open(file_path)
            
            # Collect basic information
            sheet_count = workbook.Sheets.Count
            sheet_names = [workbook.Sheets(i+1).Name for i in range(sheet_count)]
            
            # Extract macros/VBA
            vba_modules = []
            try:
                for i in range(workbook.VBProject.VBComponents.Count):
                    component = workbook.VBProject.VBComponents(i+1)
                    vba_code = component.CodeModule.Lines(1, component.CodeModule.CountOfLines)
                    if vba_code.strip():
                        vba_modules.append({
                            "name": component.Name,
                            "type": component.Type,
                            "code": vba_code
                        })
            except Exception as e:
                logger.warning(f"Could not access VBA project: {e}")
            
            # Extract formulas and data connections
            formulas = []
            connections = []
            
            for sheet_index in range(sheet_count):
                sheet = workbook.Sheets(sheet_index + 1)
                used_range = sheet.UsedRange
                
                # Check for formulas in used range
                for row in range(1, used_range.Rows.Count + 1):
                    for col in range(1, used_range.Columns.Count + 1):
                        cell = used_range.Cells(row, col)
                        if cell.HasFormula:
                            formulas.append({
                                "sheet": sheet.Name,
                                "address": cell.Address,
                                "formula": cell.Formula
                            })
            
            # Check for data connections
            for connection in workbook.Connections:
                connections.append({
                    "name": connection.Name,
                    "description": connection.Description,
                    "connection_string": getattr(connection, "ConnectionString", "")
                })
            
            # Close workbook without saving
            workbook.Close(SaveChanges=False)
            
            # Return analysis results
            analysis = {
                "file_path": file_path,
                "sheet_count": sheet_count,
                "sheet_names": sheet_names,
                "formula_count": len(formulas),
                "formulas": formulas,
                "vba_module_count": len(vba_modules),
                "vba_modules": vba_modules,
                "connection_count": len(connections),
                "connections": connections
            }
            
            # Calculate complexity score
            complexity_score = self._calculate_complexity_score(analysis)
            analysis["complexity_score"] = complexity_score
            analysis["complexity_rating"] = self._get_complexity_rating(complexity_score)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing Excel file: {e}")
            if 'workbook' in locals() and workbook:
                workbook.Close(SaveChanges=False)
            return {"error": str(e)}
        
    def _calculate_complexity_score(self, analysis):
        """Calculate a complexity score for the EUDA based on various factors"""
        score = 0
        
        # Basic factors
        score += min(analysis["sheet_count"] * 5, 30)  # Up to 30 points for sheets
        score += min(analysis["formula_count"] * 0.5, 30)  # Up to 30 points for formulas
        score += min(analysis["vba_module_count"] * 10, 40)  # Up to 40 points for VBA
        
        # Formula complexity
        complex_formula_count = 0
        for formula in analysis["formulas"]:
            formula_text = formula["formula"].lower()
            # Check for advanced Excel functions
            advanced_functions = ["vlookup", "hlookup", "index", "match", "indirect", 
                                 "offset", "sumifs", "countifs", "averageifs", "if"]
            if any(func in formula_text for func in advanced_functions):
                complex_formula_count += 1
        
        score += min(complex_formula_count * 2, 20)  # Up to 20 points for complex formulas
        
        # External connections
        score += min(analysis["connection_count"] * 15, 30)  # Up to 30 points for connections
        
        # VBA complexity
        vba_complexity = 0
        vba_code_length = 0
        for module in analysis["vba_modules"]:
            vba_code_length += len(module["code"])
            # Check for advanced VBA features
            code = module["code"].lower()
            if "createobject" in code or "getobject" in code:
                vba_complexity += 5
            if "adodb" in code:
                vba_complexity += 10
            if "sql" in code:
                vba_complexity += 10
        
        score += min(vba_code_length / 100, 20)  # Up to 20 points for code length
        score += min(vba_complexity, 30)  # Up to 30 points for VBA complexity
        
        return min(score, 100)  # Cap at 100
    
    def _get_complexity_rating(self, score):
        """Convert numerical score to qualitative rating"""
        if score < 20:
            return "Simple"
        elif score < 40:
            return "Basic"
        elif score < 60:
            return "Moderate"
        elif score < 80:
            return "Complex"
        else:
            return "Very Complex"

class VectorDatabase:
    """Class to handle vector database operations using PostgreSQL"""
    
    def __init__(self, host="localhost", port=5432, dbname="euda_db", user="postgres", password="postgres"):
        self.connection_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password
        }
        self.embedding_service = EmbeddingService()
    
    def initialize_database(self):
        """Initialize database schema"""
        try:
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()
            
            # Create tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS eudas (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    analysis JSONB NOT NULL,
                    complexity_score FLOAT NOT NULL,
                    complexity_rating TEXT NOT NULL,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS euda_embeddings (
                    id SERIAL PRIMARY KEY,
                    euda_id INTEGER REFERENCES eudas(id) ON DELETE CASCADE,
                    embedding_type TEXT NOT NULL,
                    embedding VECTOR(1536),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            return False
    
    def store_euda_analysis(self, analysis, summary=None):
        """Store EUDA analysis in the database"""
        try:
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()
            
            file_path = analysis["file_path"]
            file_name = os.path.basename(file_path)
            
            # Store EUDA metadata
            cursor.execute("""
                INSERT INTO eudas (file_path, file_name, analysis, complexity_score, complexity_rating, summary)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                file_path, 
                file_name, 
                json.dumps(analysis), 
                analysis["complexity_score"],
                analysis["complexity_rating"],
                summary
            ))
            
            euda_id = cursor.fetchone()[0]
            
            # Create and store embeddings
            if summary:
                embedding = self.embedding_service.get_embedding(summary)
                
                cursor.execute("""
                    INSERT INTO euda_embeddings (euda_id, embedding_type, embedding)
                    VALUES (%s, %s, %s)
                """, (euda_id, "summary", embedding))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return euda_id
        
        except Exception as e:
            logger.error(f"Error storing EUDA analysis: {e}")
            return None
    
    def get_all_eudas(self):
        """Get all EUDAs from the database"""
        try:
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, file_name, complexity_rating, summary
                FROM eudas
                ORDER BY created_at DESC
            """)
            
            results = cursor.fetchall()
            
            eudas = []
            for row in results:
                eudas.append({
                    "id": row[0],
                    "file_name": row[1],
                    "complexity_rating": row[2],
                    "summary": row[3]
                })
            
            cursor.close()
            conn.close()
            
            return eudas
        
        except Exception as e:
            logger.error(f"Error getting EUDAs: {e}")
            return []
    
    def get_euda_by_id(self, euda_id):
        """Get EUDA by ID"""
        try:
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, file_path, file_name, analysis, complexity_score, complexity_rating, summary
                FROM eudas
                WHERE id = %s
            """, (euda_id,))
            
            row = cursor.fetchone()
            
            if row:
                euda = {
                    "id": row[0],
                    "file_path": row[1],
                    "file_name": row[2],
                    "analysis": json.loads(row[3]),
                    "complexity_score": row[4],
                    "complexity_rating": row[5],
                    "summary": row[6]
                }
            else:
                euda = None
            
            cursor.close()
            conn.close()
            
            return euda
        
        except Exception as e:
            logger.error(f"Error getting EUDA by ID: {e}")
            return None
    
    def search_similar_eudas(self, query, limit=5):
        """Search for similar EUDAs based on vector similarity"""
        try:
            query_embedding = self.embedding_service.get_embedding(query)
            
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT e.id, e.file_name, e.complexity_rating, e.summary, 
                       1 - (ee.embedding <-> %s) as similarity
                FROM eudas e
                JOIN euda_embeddings ee ON e.id = ee.euda_id
                WHERE ee.embedding_type = 'summary'
                ORDER BY similarity DESC
                LIMIT %s
            """, (query_embedding, limit))
            
            results = cursor.fetchall()
            
            eudas = []
            for row in results:
                eudas.append({
                    "id": row[0],
                    "file_name": row[1],
                    "complexity_rating": row[2],
                    "summary": row[3],
                    "similarity": row[4]
                })
            
            cursor.close()
            conn.close()
            
            return eudas
        
        except Exception as e:
            logger.error(f"Error searching similar EUDAs: {e}")
            return []

class EmbeddingService:
    """Service to get vector embeddings using Amazon Titan models"""
    
    def __init__(self):
        # Initialize AWS Bedrock client for Amazon Titan embeddings
        self.bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=os.getenv('AWS_REGION', 'us-east-1'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        self.model_id = "amazon.titan-embed-text-v1"
    
    def get_embedding(self, text):
        """Get embedding vector for text using Amazon Titan"""
        try:
            # Prepare request body
            request_body = {
                "inputText": text
            }
            
            # Invoke model
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            
            # Parse response
            response_body = json.loads(response.get('body').read())
            embedding = response_body.get('embedding')
            
            return embedding
        
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
            # Return a zero vector as fallback
            return [0.0] * 1536

class LLMService:
    """Service to interact with Claude for analysis and code generation"""
    
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv('ANTHROPIC_API_KEY')
        )
    
    def analyze_euda(self, analysis):
        """Use Claude to analyze the EUDA and provide a summary"""
        try:
            # Prepare a prompt for Claude with the EUDA details
            formulas_str = "\n".join([f"Sheet: {f['sheet']}, Cell: {f['address']}, Formula: {f['formula']}" 
                                     for f in analysis["formulas"][:20]])  # Limit to first 20 formulas
            
            vba_code_str = ""
            for module in analysis["vba_modules"][:3]:  # Limit to first 3 modules
                vba_code_str += f"\nModule: {module['name']}\n```vb\n{module['code'][:1000]}...\n```\n"
            
            connections_str = "\n".join([f"Name: {c['name']}, Description: {c['description']}" 
                                        for c in analysis["connections"]])
            
            prompt = f"""You are an expert in analyzing Excel EUDAs (End User Developed Applications). 
            Please analyze the following Excel file and provide:
            1. A concise summary of what this EUDA appears to be doing
            2. The estimated complexity and why
            3. Key data sources identified
            4. A high-level recommendation on whether this could be migrated to a Python application
            
            Excel File: {os.path.basename(analysis['file_path'])}
            Sheets: {', '.join(analysis['sheet_names'])}
            Complexity Score: {analysis['complexity_score']}
            Complexity Rating: {analysis['complexity_rating']}
            
            # Sample Formulas:
            {formulas_str}
            
            # VBA Code (if any):
            {vba_code_str}
            
            # Data Connections:
            {connections_str}
            
            Based on this information, provide a concise analysis."""
            
            # Call Claude
            message = self.client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                system="You are an expert in Excel EUDA analysis and Python migration. Provide concise, actionable insights.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return message.content[0].text
        
        except Exception as e:
            logger.error(f"Error analyzing EUDA with Claude: {e}")
            return f"Error analyzing EUDA: {str(e)}"
    
    def generate_python_code(self, euda):
        """Generate Python code to replace Excel EUDA functionality"""
        try:
            # Extract key information from the EUDA analysis
            analysis = euda["analysis"]
            formulas_str = "\n".join([f"Sheet: {f['sheet']}, Cell: {f['address']}, Formula: {f['formula']}" 
                                     for f in analysis["formulas"][:20]])
            
            vba_code_str = ""
            for module in analysis["vba_modules"][:3]:
                vba_code_str += f"\nModule: {module['name']}\n```vb\n{module['code'][:1000]}...\n```\n"
            
            connections_str = "\n".join([f"Name: {c['name']}, Description: {c['description']}" 
                                        for c in analysis["connections"]])
            
            prompt = f"""You are an expert in converting Excel EUDAs to Python applications.
            Please generate a Python application that replicates the functionality of this EUDA.
            
            Excel File: {os.path.basename(analysis['file_path'])}
            Complexity: {analysis['complexity_rating']}
            Summary: {euda.get('summary', 'No summary available')}
            
            # Sample Formulas:
            {formulas_str}
            
            # VBA Code (if any):
            {vba_code_str}
            
            # Data Connections:
            {connections_str}
            
            Please generate a well-structured Python application that replicates this functionality.
            Use pandas for data manipulation and include proper error handling.
            If database connections are required, use SQLAlchemy.
            Include clear comments and documentation.
            Organize the code in a maintainable way using classes and functions.
            
            The application should:
            1. Load data from similar sources
            2. Implement similar business logic
            3. Produce equivalent outputs
            4. Have a simple user interface if appropriate
            
            Provide complete, working code."""
            
            # Call Claude
            message = self.client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4000,
                system="You are an expert in Python development. Generate well-structured, maintainable Python code that follows best practices.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract and return the code
            response = message.content[0].text
            
            # Look for Python code blocks in the response
            code_blocks = re.findall(r'```python\n(.*?)```', response, re.DOTALL)
            
            if code_blocks:
                # Combine all code blocks
                full_code = "\n\n".join(code_blocks)
                return full_code
            else:
                # If no code blocks are found, return the entire response
                return response
        
        except Exception as e:
            logger.error(f"Error generating Python code: {e}")
            return f"Error generating Python code: {str(e)}"

class ChatbotService:
    """Service to provide chatbot functionality for EUDA analysis and remediation"""
    
    def __init__(self):
        self.llm_service = LLMService()
        self.vector_db = VectorDatabase()
    
    def chat(self, euda_id, message):
        """Process a chat message about a specific EUDA"""
        try:
            # Get EUDA details
            euda = self.vector_db.get_euda_by_id(euda_id)
            
            if not euda:
                return "EUDA not found. Please select a valid EUDA."
            
            # Prepare a prompt for Claude with the EUDA details and user message
            analysis = euda["analysis"]
            
            prompt = f"""You are an expert assistant for Excel EUDA remediation. 
            You are helping with this specific EUDA:
            
            Excel File: {os.path.basename(analysis['file_path'])}
            Complexity: {analysis['complexity_rating']}
            Summary: {euda.get('summary', 'No summary available')}
            
            The user is asking: "{message}"
            
            Please provide a helpful, accurate response based on the EUDA details."""
            
            # Call Claude
            client = anthropic.Anthropic(
                api_key=os.getenv('ANTHROPIC_API_KEY')
            )
            
            response = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1500,
                system="You are an expert in Excel EUDA analysis and Python migration. Help users understand and remediate their EUDAs.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return response.content[0].text
        
        except Exception as e:
            logger.error(f"Error in chatbot: {e}")
            return f"Error processing your message: {str(e)}"

class AnalyzeThread(QThread):
    """Thread for analyzing Excel files in the background"""
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)
    
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.analyzer = ExcelAnalyzer()
        self.llm_service = LLMService()
        self.vector_db = VectorDatabase()
    
    def run(self):
        try:
            self.update_signal.emit("Initializing database...")
            self.vector_db.initialize_database()
            
            self.update_signal.emit("Analyzing Excel file...")
            analysis = self.analyzer.analyze_excel_file(self.file_path)
            
            if "error" in analysis:
                self.update_signal.emit(f"Error: {analysis['error']}")
                return
            
            self.update_signal.emit("Getting LLM analysis...")
            summary = self.llm_service.analyze_euda(analysis)
            
            self.update_signal.emit("Storing in database...")
            euda_id = self.vector_db.store_euda_analysis(analysis, summary)
            
            if euda_id:
                self.update_signal.emit(f"Analysis complete. EUDA ID: {euda_id}")
                
                # Get complete EUDA data
                euda = self.vector_db.get_euda_by_id(euda_id)
                self.finished_signal.emit(euda)
            else:
                self.update_signal.emit("Error storing analysis.")
        
        except Exception as e:
            self.update_signal.emit(f"Error: {str(e)}")
        
        finally:
            # Make sure to close Excel
            self.analyzer.close_excel()

class GenerateCodeThread(QThread):
    """Thread for generating Python code in the background"""
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)
    
    def __init__(self, euda):
        super().__init__()
        self.euda = euda
        self.llm_service = LLMService()
    
    def run(self):
        try:
            self.update_signal.emit("Generating Python code...")
            code = self.llm_service.generate_python_code(self.euda)
            
            self.update_signal.emit("Code generation complete.")
            self.finished_signal.emit(code)
        
        except Exception as e:
            self.update_signal.emit(f"Error: {str(e)}")
            self.finished_signal.emit(f"Error generating code: {str(e)}")

class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.excel_analyzer = ExcelAnalyzer()
        self.vector_db = VectorDatabase()
        self.chatbot_service = ChatbotService()
        
        self.current_euda = None
        self.generated_code = None
        
        self.initUI()
    
    def initUI(self):
        """Initialize the user interface"""
        self.setWindowTitle("EUDA Remediation Tool")
        self.setGeometry(100, 100, 1200, 800)
        
        # Main layout
        main_layout = QHBoxLayout()
        
        # Left panel for EUDA list
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        left_panel.setMaximumWidth(300)
        
        # Button to add new EUDA
        self.add_button = QPushButton("Analyze New EUDA")
        self.add_button.clicked.connect(self.analyze_new_euda)
        left_layout.addWidget(self.add_button)
        
        # Label for EUDA list
        left_layout.addWidget(QLabel("Analyzed EUDAs:"))
        
        # Scrollable area for EUDA list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.euda_list_widget = QWidget()
        self.euda_list_layout = QVBoxLayout()
        self.euda_list_widget.setLayout(self.euda_list_layout)
        scroll_area.setWidget(self.euda_list_widget)
        left_layout.addWidget(scroll_area)
        
        # Right panel for details
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        # EUDA details
        self.details_label = QLabel("Select an EUDA to view details")
        right_layout.addWidget(self.details_label)
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(200)
        right_layout.addWidget(self.summary_text)
        
        # Python code generation
        generate_button = QPushButton("Generate Python Code")
        generate_button.clicked.connect(self.generate_python_code)
        right_layout.addWidget(generate_button)
        
        self.code_text = QTextEdit()
        self.code_text.setReadOnly(True)
        self.code_text.setMinimumHeight(300)
        right_layout.addWidget(self.code_text)
        
        # Save code button
        save_button = QPushButton("Save Python Code")
        save_button.clicked.connect(self.save_python_code)
        right_layout.addWidget(save_button)
        
        # Chatbot
        chat_label = QLabel("Ask about this EUDA:")
        right_layout.addWidget(chat_label)
        
        self.chat_input = QTextEdit()
        self.chat_input.setMaximumHeight(60)
        right_layout.addWidget(self.chat_input)
        
        chat_button = QPushButton("Send")
        chat_button.clicked.connect(self.send_chat)
        right_layout.addWidget(chat_button)
        
        self.chat_output = QTextEdit()
        self.chat_output.setReadOnly(True)
        self.chat_output.setMinimumHeight(150)
        right_layout.addWidget(self.chat_output)
        
        # Add panels to main layout
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)
        
        # Set main layout
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Load EUDAs from database
        self.load_eudas()
    
    def load_eudas(self):
        """Load EUDAs from database and display in the list"""
        eudas = self.vector_db.get_all_eudas()
        
        # Clear existing items
        for i in reversed(range(self.euda_list_layout.count())):
            widget = self.euda_list_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # Add EUDAs to the list
        for euda in eudas:
            button = QPushButton(f"{euda['file_name']} ({euda['complexity_rating']})")
            button.setProperty("euda_id", euda["id"])
            button.clicked.connect(lambda checked, id=euda["id"]: self.load_euda_details(id))
            self.euda_list_layout.addWidget(button)
        
        # Add stretch to push buttons to the top
        self.euda_list_layout.addStretch()
    
    def