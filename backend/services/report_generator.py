"""
report_generator.py — TenderAI world-class PDF export
9 sections: Cover · Executive Summary · Compliance Matrix · Vendor Scorecards ·
            Risk Findings · Admin Eligibility · Decision Trail · Evidence Appendix · Methodology
"""
from __future__ import annotations
import logging, os
from datetime import datetime
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
logger = logging.getLogger(__name__)

C_NAVY=colors.HexColor("#1B2A4A"); C_GREEN=colors.HexColor("#059669"); C_GREEN_BG=colors.HexColor("#ECFDF5")
C_AMBER=colors.HexColor("#D97706"); C_AMBER_BG=colors.HexColor("#FFFBEB")
C_RED=colors.HexColor("#DC2626"); C_RED_BG=colors.HexColor("#FEF2F2")
C_PURPLE=colors.HexColor("#7C3AED"); C_PURPLE_BG=colors.HexColor("#EDE9FE")
C_GRAY_LT=colors.HexColor("#F5F5F3"); C_GRAY_MD=colors.HexColor("#D3D1C7")
C_TEXT=colors.HexColor("#111318"); C_MUTED=colors.HexColor("#52525B"); C_SUB=colors.HexColor("#A1A1AA")
C_WHITE=colors.white; C_TEAL=colors.HexColor("#0C7B72")

STATUS_COLOUR={"FULL":(C_GREEN,C_GREEN_BG),"PARTIAL":(C_AMBER,C_AMBER_BG),"NONE":(C_RED,C_RED_BG),"AMBIGUOUS":(C_PURPLE,C_PURPLE_BG),"PENDING":(C_MUTED,C_GRAY_LT)}
SEV_COLOUR={"Critical":(C_WHITE,C_RED),"High":(C_WHITE,C_AMBER),"Medium":(C_TEXT,C_AMBER_BG),"Low":(C_TEXT,C_GREEN_BG)}
DECISION_COLOUR={"ACCEPTED":(C_GREEN,C_GREEN_BG,"✓ Accepted"),"ANNOTATED":(C_AMBER,C_AMBER_BG,"✎ Annotated"),"OVERRIDDEN":(C_RED,C_RED_BG,"✗ Overridden")}

def _s(name,**kw):
    b=getSampleStyleSheet()["Normal"]; return ParagraphStyle(name,parent=b,**kw)

def _styles():
    return {
        "cover_title":_s("ct",fontSize=30,leading=36,textColor=C_WHITE,fontName="Helvetica-Bold",alignment=TA_CENTER,spaceAfter=6),
        "cover_sub":_s("cs",fontSize=14,leading=18,textColor=colors.HexColor("#B0C4D8"),fontName="Helvetica",alignment=TA_CENTER,spaceAfter=4),
        "cover_meta":_s("cm",fontSize=10,leading=14,textColor=colors.HexColor("#8EA8C3"),fontName="Helvetica",alignment=TA_CENTER),
        "h1":_s("h1",fontSize=14,leading=18,textColor=C_NAVY,fontName="Helvetica-Bold",spaceBefore=18,spaceAfter=6),
        "h2":_s("h2",fontSize=11,leading=14,textColor=C_NAVY,fontName="Helvetica-Bold",spaceBefore=12,spaceAfter=4),
        "body":_s("bd",fontSize=9,leading=13,textColor=C_TEXT,fontName="Helvetica",spaceAfter=4),
        "body_sm":_s("bsm",fontSize=8,leading=11,textColor=C_MUTED,fontName="Helvetica",spaceAfter=2),
        "th":_s("th",fontSize=8,leading=10,textColor=C_WHITE,fontName="Helvetica-Bold",alignment=TA_CENTER),
        "td":_s("td",fontSize=8,leading=11,textColor=C_TEXT,fontName="Helvetica"),
        "td_c":_s("tdc",fontSize=8,leading=11,textColor=C_TEXT,fontName="Helvetica",alignment=TA_CENTER),
        "mono":_s("mn",fontSize=7,leading=10,textColor=C_MUTED,fontName="Courier"),
        "disclaimer":_s("dis",fontSize=7,leading=10,textColor=C_RED,fontName="Helvetica-Oblique",alignment=TA_CENTER),
        "methodology":_s("me",fontSize=8,leading=12,textColor=C_MUTED,fontName="Helvetica-Oblique"),
        "quote":_s("qt",fontSize=8,leading=12,textColor=C_MUTED,fontName="Helvetica-Oblique",leftIndent=10,spaceAfter=4),
    }

def _hf(canvas,doc):
    canvas.saveState(); W,H=A4
    canvas.setFont("Helvetica",7); canvas.setFillColor(C_SUB); canvas.setStrokeColor(C_GRAY_MD); canvas.setLineWidth(0.5)
    canvas.line(2*cm,H-1.4*cm,W-2*cm,H-1.4*cm)
    canvas.drawString(2*cm,H-1.1*cm,"TENDER COMPLIANCE AUDIT REPORT")
    canvas.drawRightString(W-2*cm,H-1.1*cm,getattr(doc,"project_name",""))
    canvas.line(2*cm,1.5*cm,W-2*cm,1.5*cm)
    canvas.drawString(2*cm,1.0*cm,getattr(doc,"report_date",""))
    canvas.drawString(W/2-1.5*cm,1.0*cm,"CONFIDENTIAL")
    canvas.drawRightString(W-2*cm,1.0*cm,f"Page {doc.page}")
    canvas.restoreState()

class ReportGenerator:
    def generate(self,project_name,vendor_scores,requirements,matches,risk_findings,admin_checks=None,decisions=None,output_path="reports/audit_report.pdf"):
        os.makedirs(os.path.dirname(os.path.abspath(output_path)),exist_ok=True)
        ST=_styles(); rd=datetime.now().strftime("%d %B %Y, %H:%M")
        doc=BaseDocTemplate(output_path,pagesize=A4,leftMargin=2*cm,rightMargin=2*cm,topMargin=2.5*cm,bottomMargin=2.5*cm)
        doc.project_name=project_name; doc.report_date=rd
        bf=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,id="body")
        cf=Frame(0,0,A4[0],A4[1],id="cover")
        doc.addPageTemplates([PageTemplate(id="cover_page",frames=[cf]),PageTemplate(id="body_page",frames=[bf],onPage=_hf)])
        story=[]
        story+=self._cover(project_name,vendor_scores,rd,ST)
        story.append(PageBreak())
        story+=self._exec_summary(vendor_scores,requirements,risk_findings,decisions,ST)
        story.append(PageBreak())
        story+=self._matrix(vendor_scores,requirements,matches,ST)
        story.append(PageBreak())
        story+=self._scorecards(vendor_scores,requirements,matches,risk_findings,ST)
        story.append(PageBreak())
        story+=self._risks(vendor_scores,risk_findings,ST)
        if admin_checks:
            story+=self._admin(vendor_scores,admin_checks,ST)
        if decisions:
            story.append(PageBreak())
            story+=self._decision_trail(vendor_scores,requirements,matches,decisions,ST)
        story+=self._evidence_appendix(vendor_scores,requirements,matches,ST)
        story+=self._methodology(ST)
        doc.build(story)
        logger.info("PDF generated: %s",output_path)
        return str(Path(output_path).resolve())

    def _vendor_cards(self, vs_list):
        n = max(len(vs_list), 1)
        cw = (A4[0] - 4*cm) / n
        data = [[]]

        cmds = [
            ("GRID",(0,0),(-1,-1),0.5,C_GRAY_MD),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ALIGN",(0,0),(-1,-1),"CENTER"),
            ("TOPPADDING",(0,0),(-1,-1),14),
            ("BOTTOMPADDING",(0,0),(-1,-1),14),
        ]

        for i, vs in enumerate(vs_list):
            sc = vs.get("compliance_score", 0)
            cs = vs.get("status_colour", "amber")

            # text + background colors
            tc = {"green": C_GREEN, "amber": C_AMBER, "red": C_RED}.get(cs, C_AMBER)
            bg = {"green": C_GREEN_BG, "amber": C_AMBER_BG, "red": C_RED_BG}.get(cs, C_AMBER_BG)

            cell = [
                Paragraph(
                    vs.get("vendor_name", "Vendor"),
                    _s(f"vn{i}", fontSize=10, fontName="Helvetica-Bold",
                    alignment=TA_CENTER, textColor=C_TEXT)
                ),

                Spacer(1, 8),

                Paragraph(
                    f"{sc:.0f}%",
                    _s(f"vsc{i}", fontSize=28, fontName="Helvetica-Bold",
                    alignment=TA_CENTER, textColor=tc)
                )
            ]

            data[0].append(cell)

            # keep background color (your requirement)
            cmds.append(("BACKGROUND", (i, 0), (i, 0), bg))

        t = Table(data, colWidths=[cw]*n, rowHeights=[120])
        t.setStyle(TableStyle(cmds))
        return t

    def _cover(self,pname,vs,rd,ST):
        W,H=A4; story=[]
        bg=Table([[""]],colWidths=[W],rowHeights=[H*0.40])
        bg.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_NAVY),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
        story.append(bg); story.append(Spacer(1,-H*0.40+3*cm))
        story.append(Paragraph("TENDER COMPLIANCE",ST["cover_sub"])); story.append(Paragraph("AUDIT REPORT",ST["cover_title"]))
        story.append(Paragraph(pname,ST["cover_sub"])); story.append(Spacer(1,0.4*cm))
        story.append(Paragraph(f"Generated: {rd}",ST["cover_meta"])); story.append(Paragraph("CONFIDENTIAL — NOT FOR DISTRIBUTION",ST["cover_meta"]))
        story.append(Spacer(1,H*0.40-8*cm))
        if vs: story.append(Paragraph("VENDOR COMPLIANCE SUMMARY",ST["h1"])); story.append(self._vendor_cards(vs)); story.append(Spacer(1,0.5*cm))
        toc=[["Section","Page"],["1. Executive Summary","2"],["2. Compliance Matrix","3"],["3. Vendor Scorecards","4"],["4. Risk Findings","5"],["5. Admin Eligibility","6"],["6. Decision Trail","7"],["7. Evidence Appendix","8"],["8. Methodology","9"]]
        tt=Table(toc,colWidths=[11*cm,2*cm])
        tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_GRAY_LT]),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("ALIGN",(1,0),(1,-1),"CENTER")]))
        story.append(tt); return story

    def _exec_summary(self,vs,reqs,risks,decisions,ST):
        story=[Paragraph("1. EXECUTIVE SUMMARY",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),Spacer(1,0.2*cm)]
        rec=self._recommended(vs)
        if rec:
            rb=Table([[Paragraph(f"<b>AI Award Recommendation: {rec['vendor_name']}</b><br/>Highest compliance score ({rec['compliance_score']:.0f}%) with no critical risks.",_s("rec",fontSize=9,leading=13,textColor=C_TEAL))]],colWidths=[A4[0]-4*cm])
            rb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_GREEN_BG),("BOX",(0,0),(-1,-1),1.5,C_GREEN),("LEFTPADDING",(0,0),(-1,-1),12),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)]))
            story+=[rb,Spacer(1,0.4*cm)]
        total=len(reqs); mand=sum(1 for r in reqs if r.get("criticality")=="Mandatory")
        crit=sum(1 for r in risks if r.get("severity") in ("Critical","CRITICAL"))
        dec_count=len(decisions) if decisions else 0; overrides=sum(1 for d in (decisions or []) if d.get("decision_type")=="OVERRIDDEN")
        md=[["Metric","Value"],["Total Requirements",str(total)],["Mandatory Requirements",str(mand)],["Vendors Evaluated",str(len(vs))],["Critical Risks",str(crit)],["Human Decisions",str(dec_count)],["Reviewer Overrides",str(overrides)]]
        mt=Table(md,colWidths=[9*cm,5*cm])
        mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_GRAY_LT]),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story+=[mt,Spacer(1,0.4*cm)]
        for v in vs:
            story.append(Paragraph(v.get("vendor_name","Vendor"),ST["h2"]))
            sc=v.get("compliance_score",0); cs=v.get("status_colour","amber"); tc={"green":C_GREEN,"amber":C_AMBER,"red":C_RED}.get(cs,C_AMBER)
            vrisks=[r for r in risks if r.get("vendor_document_id")==v.get("vendor_document_id")]
            crit_v=sum(1 for r in vrisks if r.get("severity") in ("Critical","CRITICAL"))
            sd=[["Compliance Score",f"{sc:.1f}%","Status",cs.upper()],["Mandatory FULL",str(v.get("mandatory_full",0)),"Critical Risks",str(crit_v)],["Partial",str(v.get("mandatory_partial",0)),"High Risks",str(v.get("high_risks",0))],["Missing",str(v.get("mandatory_none",0)),"Risk Score",f"{v.get('risk_score',0):.1f}"]]
            st2=Table(sd,colWidths=[4.5*cm,3*cm,4.5*cm,3*cm])
            st2.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("ROWBACKGROUNDS",(0,0),(-1,-1),[C_WHITE,C_GRAY_LT]),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("TEXTCOLOR",(1,0),(1,0),tc),("FONTNAME",(1,0),(1,0),"Helvetica-Bold")]))
            story.append(KeepTogether([st2,Spacer(1,0.3*cm)]))
        return story

    def _recommended(self,vs):
        cands=[v for v in vs if v.get("critical_risks",0)==0] or vs
        return max(cands,key=lambda v:v.get("compliance_score",0),default=None)

    def _matrix(self,vs,reqs,matches,ST):
        story=[Paragraph("2. COMPLIANCE MATRIX",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),
               Paragraph("GREEN=FULL, AMBER=PARTIAL, RED=NONE, PURPLE=AMBIGUOUS. M=Mandatory, R=Recommended. Confidence % shown.",_s("msc",fontSize=7,leading=10,textColor=C_MUTED)),Spacer(1,0.3*cm)]
        mlook={(m.get("requirement_id"),m.get("vendor_document_id")):m for m in matches}
        vids=[v.get("vendor_document_id") for v in vs]; vnames=[v.get("vendor_name",f"V{i+1}") for i,v in enumerate(vs)]
        PW=A4[0]-4*cm; vcw=2.2*cm; rcw=max(PW-vcw*len(vids)-1.8*cm-0.8*cm,4*cm)
        hdr=[Paragraph("#",ST["th"]),Paragraph("Requirement",ST["th"])]+[Paragraph(n[:14],ST["th"]) for n in vnames]
        cmds=[("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("ALIGN",(0,0),(1,-1),"LEFT")]
        data=[hdr]
        for ri,req in enumerate(reqs):
            rid=req.get("id"); clause=req.get("rfp_clause_ref",str(rid)); intent=(req.get("normalised_intent") or req.get("raw_text",""))[:80]; ca="M" if req.get("criticality")=="Mandatory" else "R"
            row=[Paragraph(f"{clause}\n{ca}",ST["td_c"]),Paragraph(intent,ST["td"])]
            for j,vid in enumerate(vids):
                m=mlook.get((rid,vid)); status=m.get("status","NONE") if m else "NONE"
                conf=m.get("confidence",0) if m else 0; cp=int((conf if conf<=1 else conf/100)*100)
                tc,bg=STATUS_COLOUR.get(status,(C_MUTED,C_GRAY_LT)); abbr={"FULL":"Full","PARTIAL":"Part.","NONE":"None","AMBIGUOUS":"Ambig.","PENDING":"—"}.get(status,status)
                row.append(Paragraph(f"{abbr}\n{cp}%",_s(f"sc{ri}{j}",fontSize=7,leading=10,textColor=tc,alignment=TA_CENTER,fontName="Helvetica-Bold")))
                ar=ri+1; col=2+j
                cmds+=[(("BACKGROUND",(col,ar),(col,ar),bg)),("TEXTCOLOR",(col,ar),(col,ar),tc),("ALIGN",(col,ar),(col,ar),"CENTER")]
            data.append(row)
            if ri%2==0: cmds.append(("BACKGROUND",(0,ri+1),(1,ri+1),C_GRAY_LT))
        cws=[0.8*cm,rcw]+[vcw]*len(vids); mt=Table(data,colWidths=cws,repeatRows=1); mt.setStyle(TableStyle(cmds)); story.append(mt); return story

    def _scorecards(self,vs,reqs,matches,risks,ST):
        story=[Paragraph("3. VENDOR SCORECARDS",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD)]
        mlook={(m["requirement_id"],m["vendor_document_id"]):m for m in matches}
        for v in vs:
            vid=v.get("vendor_document_id"); name=v.get("vendor_name","Vendor"); sc=v.get("compliance_score",0)
            cs=v.get("status_colour","amber"); tc={"green":C_GREEN,"amber":C_AMBER,"red":C_RED}.get(cs,C_AMBER)
            story+=[Spacer(1,0.3*cm),Paragraph(name,ST["h2"])]
            vrisks=[r for r in risks if r.get("vendor_document_id")==vid]; crit=[r for r in vrisks if r.get("severity") in ("Critical","CRITICAL")]
            gaps=[req for req in reqs if mlook.get((req["id"],vid),{}).get("status","NONE")=="NONE"]
            dd=[["Metric","Count","Metric","Count"],["FULL matches",str(v.get("mandatory_full",0)),"Critical risks",str(len(crit))],["PARTIAL",str(v.get("mandatory_partial",0)),"Risk score",f"{v.get('risk_score',0):.1f}"],["NONE (gaps)",str(v.get("mandatory_none",0)),"High risks",str(v.get("high_risks",0))]]
            dt=Table(dd,colWidths=[4*cm,2*cm,4*cm,2*cm])
            dt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_GRAY_LT]),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
            story.append(KeepTogether([dt]))
            if gaps:
                story+=[Spacer(1,0.2*cm),Paragraph("Missing requirements:",_s("glh",fontSize=8,fontName="Helvetica-Bold",textColor=C_RED))]
                for req in gaps[:5]: story.append(Paragraph(f"• {req.get('rfp_clause_ref','')} — {(req.get('normalised_intent') or req.get('raw_text',''))[:100]}",_s("gli",fontSize=7,leading=10,textColor=C_MUTED,leftIndent=10)))
                if len(gaps)>5: story.append(Paragraph(f"  … and {len(gaps)-5} more (see matrix)",_s("glm",fontSize=7,textColor=C_MUTED)))
            story.append(HRFlowable(width="100%",thickness=0.5,color=C_GRAY_MD,spaceAfter=4))
        return story

    def _risks(self,vs,risks,ST):
        story=[Paragraph("4. RISK FINDINGS",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),Spacer(1,0.2*cm)]
        if not risks: story.append(Paragraph("No risk findings detected.",ST["body"])); return story
        vmap={v.get("vendor_document_id"):v.get("vendor_name","Unknown") for v in vs}
        so={"Critical":0,"CRITICAL":0,"High":1,"HIGH":1,"Medium":2,"MEDIUM":2,"Low":3,"LOW":3}
        for risk in sorted(risks,key=lambda r:so.get(r.get("severity","Low"),3)):
            sev=risk.get("severity","Low").capitalize(); tc,bg=SEV_COLOUR.get(sev,(C_TEXT,C_GRAY_LT))
            vname=vmap.get(risk.get("vendor_document_id"),"Unknown"); phrase=risk.get("matched_phrase",""); impact=risk.get("impact_explanation",""); sec=risk.get("section_ref",""); rfp=risk.get("rfp_clause_ref",""); conf="✓ AI Confirmed" if risk.get("confirmed_by_llm") else "Pattern Match"
            cd=[[Paragraph(sev.upper(),_s(f"rs{sev}",fontSize=8,fontName="Helvetica-Bold",textColor=tc,alignment=TA_CENTER)),Paragraph(f"<b>{vname}</b> — {risk.get('risk_type','').replace('_',' ').title()}",ST["td"])],["",Paragraph(f'"{phrase}"',ST["quote"])],["",Paragraph(f"<b>Impact:</b> {impact}",ST["body_sm"])],["",Paragraph(f"Location: {sec}  ·  RFP: {rfp}  ·  {conf}",ST["body_sm"])]]
            ct=Table(cd,colWidths=[1.6*cm,A4[0]-4*cm-1.6*cm])
            ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),bg),("BACKGROUND",(1,0),(1,0),C_GRAY_LT),("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(0,0),(0,-1),"CENTER"),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("SPAN",(0,1),(0,-1))]))
            story.append(KeepTogether([ct,Spacer(1,0.2*cm)]))
        return story

    def _admin(self,vs,checks,ST):
        story=[Spacer(1,0.4*cm),Paragraph("5. ADMINISTRATIVE ELIGIBILITY",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),Paragraph("MISSING items may result in automatic disqualification.",_s("asc",fontSize=8,textColor=C_MUTED)),Spacer(1,0.3*cm)]
        vmap={v.get("vendor_document_id"):v.get("vendor_name") for v in vs}; bv={}
        for c in checks: bv.setdefault(c.get("vendor_document_id"),[]).append(c)
        for vid,vc in bv.items():
            story.append(Paragraph(vmap.get(vid,f"V{vid}"),ST["h2"]))
            ad=[["Document","Status","Reference"]]+[[c.get("item_name",""),"✓ FOUND" if c.get("status")=="FOUND" else "✗ MISSING",c.get("page_reference","—")] for c in vc]
            at=Table(ad,colWidths=[8*cm,2.5*cm,4.5*cm])
            cmds2=[("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_GRAY_LT]),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("ALIGN",(1,0),(1,-1),"CENTER")]
            for ri,c in enumerate(vc,1): ok=c.get("status")=="FOUND"; cmds2+=[(("TEXTCOLOR",(1,ri),(1,ri),C_GREEN if ok else C_RED)),("FONTNAME",(1,ri),(1,ri),"Helvetica-Bold")]
            at.setStyle(TableStyle(cmds2)); story+=[at,Spacer(1,0.3*cm)]
        return story

    def _decision_trail(self,vs,reqs,matches,decisions,ST):
        story=[Paragraph("6. HUMAN DECISION TRAIL",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),
               Paragraph("Every Accept / Annotate / Override decision made by reviewers. Override verdicts supersede AI classifications and are highlighted in red. This section is the legally-defensible audit trail.",_s("dtsc",fontSize=8,leading=12,textColor=C_MUTED)),Spacer(1,0.3*cm)]
        if not decisions: story.append(Paragraph("No human decisions recorded for this audit.",ST["body"])); return story
        rmap={str(r["id"]):r for r in reqs}; vmap={v.get("vendor_document_id"):v.get("vendor_name") for v in vs}
        mlook={} 
        for m in matches: mlook[(str(m.get("requirement_id","")),m.get("vendor_document_id",""))]=m
        hdr=["Requirement","Vendor","AI Verdict","Decision","Override","Reviewer","Note","Time"]
        data=[hdr]
        for d in decisions:
            rid=str(d.get("requirement_id","")); vid=d.get("vendor_document_id")
            req=rmap.get(rid,{}); rl=req.get("rfp_clause_ref",rid) or rid; rt=(req.get("normalised_intent") or req.get("raw_text",""))[:45]
            vname=vmap.get(vid,f"V{vid}"); m=mlook.get((rid,vid),{}); aiv=m.get("status","—")
            dts=d.get("decision_type",""); tc,bg,lbl=DECISION_COLOUR.get(dts,(C_TEXT,C_WHITE,dts))
            ov=d.get("override_status") or "—"; rev=d.get("reviewer_name") or "Anon"; note=(d.get("reviewer_note") or "")[:55]
            da=d.get("decided_at",""); da=da.replace("T"," ")[:16] if da and "T" in str(da) else str(da)[:16]
            data.append([
                Paragraph(f"{rl}\n{rt}",_s(f"dr{len(data)}",fontSize=6,leading=8,textColor=C_TEXT)),
                Paragraph(vname[:16],ST["td"]),
                Paragraph(aiv,_s(f"dav{len(data)}",fontSize=7,fontName="Helvetica-Bold",textColor=STATUS_COLOUR.get(aiv,(C_MUTED,C_WHITE))[0],alignment=TA_CENTER)),
                Paragraph(lbl,_s(f"dlbl{len(data)}",fontSize=7,fontName="Helvetica-Bold",textColor=tc,alignment=TA_CENTER)),
                Paragraph(ov if ov!="—" else "—",_s(f"dov{len(data)}",fontSize=7,fontName="Helvetica-Bold",textColor=C_RED if ov!="—" else C_MUTED,alignment=TA_CENTER)),
                Paragraph(rev[:16],ST["td"]),Paragraph(note or "—",_s(f"dnt{len(data)}",fontSize=6,leading=8,textColor=C_MUTED)),Paragraph(da,ST["mono"]),
            ])
        cws=[3.0*cm,2.2*cm,1.6*cm,1.8*cm,1.6*cm,2.0*cm,2.8*cm,2.0*cm]
        dt=Table(data,colWidths=cws,repeatRows=1)
        cmds=[("BACKGROUND",(0,0),(-1,0),C_NAVY),("TEXTCOLOR",(0,0),(-1,0),C_WHITE),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),7),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_GRAY_LT]),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),4)]
        for ri in range(1,len(data)):
            d2=decisions[ri-1]; dts=d2.get("decision_type",""); tc2,bg2,_=DECISION_COLOUR.get(dts,(C_TEXT,C_WHITE,""))
            cmds+=[(("BACKGROUND",(3,ri),(3,ri),bg2)),("TEXTCOLOR",(3,ri),(3,ri),tc2)]
        dt.setStyle(TableStyle(cmds)); story.append(dt)
        acc=sum(1 for d in decisions if d.get("decision_type")=="ACCEPTED"); ann=sum(1 for d in decisions if d.get("decision_type")=="ANNOTATED"); ov2=sum(1 for d in decisions if d.get("decision_type")=="OVERRIDDEN")
        story+=[Spacer(1,0.3*cm),Paragraph(f"Total: {len(decisions)}  ·  Accepted: {acc}  ·  Annotated: {ann}  ·  Overridden: {ov2}",_s("dts",fontSize=8,textColor=C_MUTED,alignment=TA_CENTER))]
        return story

    def _evidence_appendix(self,vs,reqs,matches,ST):
        story=[PageBreak(),Paragraph("7. EVIDENCE APPENDIX",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),
               Paragraph("Verbatim evidence quotes for all FULL and PARTIAL verdicts. These are the exact passages the AI classification was based on.",_s("esc",fontSize=8,textColor=C_MUTED)),Spacer(1,0.3*cm)]
        vmap={v.get("vendor_document_id"):v.get("vendor_name") for v in vs}; rmap={r["id"]:r for r in reqs}; shown=0
        for m in matches:
            if m.get("status") not in ("FULL","PARTIAL"): continue
            if not m.get("evidence_quote"): continue
            req=rmap.get(m.get("requirement_id"),{}); vname=vmap.get(m.get("vendor_document_id"),"Unknown")
            clause=req.get("rfp_clause_ref",str(req.get("id",""))); intent=(req.get("normalised_intent") or req.get("raw_text",""))[:80]
            status=m.get("status",""); tc,_=STATUS_COLOUR.get(status,(C_MUTED,C_WHITE))
            conf=m.get("confidence",0); cp=int((conf if conf<=1 else conf/100)*100); sec=m.get("section_ref","")
            ed=[[Paragraph(f"<b>{clause}</b> — {vname}",_s(f"eh{shown}",fontSize=8,fontName="Helvetica-Bold",textColor=C_NAVY)),Paragraph(f"{status}  {cp}%",_s(f"es{shown}",fontSize=8,fontName="Helvetica-Bold",textColor=tc,alignment=TA_RIGHT))],
                [Paragraph(intent,_s(f"ei{shown}",fontSize=7,textColor=C_MUTED)),""],
                [Paragraph(f'"{m["evidence_quote"][:300]}"',ST["quote"]),""],
                [Paragraph(f"Source: {sec}",ST["mono"]),""],]
            et=Table(ed,colWidths=[A4[0]-4*cm-2.5*cm,2.5*cm])
            et.setStyle(TableStyle([("SPAN",(0,1),(1,1)),("SPAN",(0,2),(1,2)),("SPAN",(0,3),(1,3)),("BACKGROUND",(0,0),(-1,0),C_GRAY_LT),("GRID",(0,0),(-1,-1),0.3,C_GRAY_MD),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
            story.append(KeepTogether([et,Spacer(1,0.2*cm)])); shown+=1
        if not shown: story.append(Paragraph("No evidence quotes available.",ST["body"]))
        return story

    def _methodology(self,ST):
        story=[PageBreak(),Paragraph("8. METHODOLOGY NOTE",ST["h1"]),HRFlowable(width="100%",thickness=1,color=C_GRAY_MD),Spacer(1,0.2*cm)]
        story.append(Paragraph("This report was generated by TenderAI using a two-stage retrieval pipeline: bi-encoder semantic search (all-MiniLM-L6-v2) retrieves top-20 candidate passages; cross-encoder reranking (ms-marco-MiniLM-L-6-v2) scores query-passage pairs jointly. Compliance classification uses Groq Llama 3.3 70B for natural language inference. Negative space detection marks NONE without LLM invocation when reranker score falls below a calibrated threshold (≈80% cost reduction). Risk detection uses 15 regex patterns confirmed by LLM contextual evaluation. Human decisions (Accept/Annotate/Override) in Section 6 supersede AI verdicts where they differ.",ST["methodology"]))
        story+=[Spacer(1,0.3*cm),Paragraph("DISCLAIMER: Computer-generated. Must be reviewed by a qualified procurement professional before use in bid evaluation or contract award decisions.",ST["disclaimer"])]
        return story

def generate_report(project_name,vendor_scores,requirements,matches,risk_findings,admin_checks=None,decisions=None,output_path="reports/audit_report.pdf"):
    return ReportGenerator().generate(project_name=project_name,vendor_scores=vendor_scores,requirements=requirements,matches=matches,risk_findings=risk_findings,admin_checks=admin_checks,decisions=decisions,output_path=output_path)