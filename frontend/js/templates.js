/**
 * Template Management Frontend Module
 */

export class TemplateManagerUI {
  constructor() {
    this.activeTemplate = "technical_report.docx";
  }

  setTemplate(name) {
    this.activeTemplate = name;
  }
}
