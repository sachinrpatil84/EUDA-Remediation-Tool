def analyze_new_euda(self):
        """Open file dialog to select and analyze a new EUDA"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Excel EUDA", "", "Excel Files (*.xlsx *.xlsm *.xls)")
        
        if file_path:
            # Show progress dialog
            progress_dialog = QMessageBox(self)
            progress_dialog.setWindowTitle("Analyzing EUDA")
            progress_dialog.setText("Initializing analysis...")
            progress_dialog.setStandardButtons(QMessageBox.NoButton)
            progress_dialog.show()
            
            # Start analysis thread
            self.analyze_thread = AnalyzeThread(file_path)
            self.analyze_thread.update_signal.connect(progress_dialog.setText)
            self.analyze_thread.finished_signal.connect(self.analysis_complete)
            self.analyze_thread.finished_signal.connect(progress_dialog.accept)
            self.analyze_thread.start()
    
    def analysis_complete(self, euda):
        """Handle completion of EUDA analysis"""
        if euda:
            self.current_euda = euda
            self.load_euda_details(euda["id"])
            
            # Refresh EUDA list
            self.load_eudas()
    
    def load_euda_details(self, euda_id):
        """Load and display details for the selected EUDA"""
        euda = self.vector_db.get_euda_by_id(euda_id)
        
        if euda:
            self.current_euda = euda
            
            # Update details
            self.details_label.setText(f"EUDA: {euda['file_name']} (Complexity: {euda['complexity_rating']})")
            self.summary_text.setText(euda.get('summary', 'No summary available'))
            
            # Clear other fields
            self.code_text.clear()
            self.chat_output.clear()
            self.generated_code = None
    
    def generate_python_code(self):
        """Generate Python code for the selected EUDA"""
        if not self.current_euda:
            QMessageBox.warning(self, "No EUDA Selected", "Please select an EUDA first.")
            return
        
        # Show progress dialog
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("Generating Code")
        progress_dialog.setText("Initializing code generation...")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.show()
        
        # Start code generation thread
        self.code_thread = GenerateCodeThread(self.current_euda)
        self.code_thread.update_signal.connect(progress_dialog.setText)
        self.code_thread.finished_signal.connect(self.code_generation_complete)
        self.code_thread.finished_signal.connect(progress_dialog.accept)
        self.code_thread.start()
    
    def code_generation_complete(self, code):
        """Handle completion of code generation"""
        self.generated_code = code
        self.code_text.setText(code)
    
    def save_python_code(self):
        """Save generated Python code to a file"""
        if not self.generated_code:
            QMessageBox.warning(self, "No Code Generated", "Please generate code first.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Python Code", "", "Python Files (*.py)")
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(self.generated_code)
                QMessageBox.information(self, "Code Saved", f"Python code saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error saving code: {str(e)}")
    
    def send_chat(self):
        """Send a chat message about the current EUDA"""
        if not self.current_euda:
            QMessageBox.warning(self, "No EUDA Selected", "Please select an EUDA first.")
            return
        
        message = self.chat_input.toPlainText().strip()
        
        if not message:
            return
        
        self.chat_output.append(f"You: {message}")
        self.chat_input.clear()
        
        # Process in the main thread for simplicity
        # In a production app, this should be in a separate thread
        try:
            response = self.chatbot_service.chat(self.current_euda["id"], message)
            self.chat_output.append(f"Assistant: {response}")
        except Exception as e:
            self.chat_output.append(f"Error: {str(e)}")

if __name__ == "__main__":
    # Create application
    app = QApplication(sys.argv)
    
    # Check environment variables
    if not os.getenv('ANTHROPIC_API_KEY'):
        QMessageBox.critical(None, "Configuration Error", 
                             "ANTHROPIC_API_KEY environment variable is not set. Please set it in the .env file.")
        sys.exit(1)
    
    if not os.getenv('AWS_ACCESS_KEY_ID') or not os.getenv('AWS_SECRET_ACCESS_KEY'):
        QMessageBox.critical(None, "Configuration Error", 
                             "AWS credentials are not set. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the .env file.")
        sys.exit(1)
    
    # Create and show the main window
    main_window = MainWindow()
    main_window.show()
    
    # Run the application
    sys.exit(app.exec_())
