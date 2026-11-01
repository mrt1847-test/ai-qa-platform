"""Bounded read projection of stored usage facts; never invent unknown totals."""

def usage_view(connection, project):
    rows=connection.execute('''SELECT role,measurement_status,COUNT(*) FROM item_usage_facts
        WHERE project_id=? GROUP BY role,measurement_status''',(str(project),)).fetchall()
    adjustments=int(connection.execute('SELECT COUNT(*) FROM usage_adjustments WHERE project_id=?',(str(project),)).fetchone()[0])
    recent=connection.execute('''SELECT kind,role,measurement_status,amount,currency,commit_seq FROM (
        SELECT 'original' AS kind,role,measurement_status,amount,currency,commit_seq,usage_id AS id FROM item_usage_facts WHERE project_id=?
        UNION ALL SELECT 'adjustment',role,measurement_status,amount,currency,commit_seq,adjustment_id FROM usage_adjustments WHERE project_id=?
        ) ORDER BY commit_seq DESC,id DESC LIMIT 10''',(str(project),str(project))).fetchall()
    return {'facts':sum(int(row[2]) for row in rows),'adjustments':adjustments,
            'statuses':[{'role':str(row[0]),'status':str(row[1]),'count':int(row[2])} for row in rows],
            'recent':[{'kind':str(row[0]),'role':str(row[1]),'status':str(row[2]),'amount':row[3],'currency':row[4],'seq':int(row[5])} for row in recent]}
