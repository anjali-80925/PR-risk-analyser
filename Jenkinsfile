pipeline {
  parameters {
    string(name: 'JIRA_IDS', description: 'JIRA ticket IDs, comma-separated (e.g. DTB-123,DTB-456)', trim: true)
    choice(name: 'COMMIT_FILTER_MODE', choices: ['only','any'], description: 'Commit filter mode: only (for ticket specific analysis), any (for regression analysis)')
  }

  agent any

  options {
    timestamps()
    timeout(time: 15, unit: 'MINUTES')
  }

  stages {
    stage('Analyze') {
      steps {
        script {
          if (!params.JIRA_IDS?.trim()) error('Provide JIRA_IDS parameter')
          
          // Auto-detect credential from SCM configuration
          def credentialId = scm.userRemoteConfigs[0].credentialsId
          echo "Using Git credential ID: ${credentialId}"
          
          withCredentials([sshUserPrivateKey(credentialsId: credentialId, keyFileVariable: 'SSH_KEY')]) {
            withEnv(["COMMIT_FILTER_MODE=${params.COMMIT_FILTER_MODE}", "JIRA_IDS=${params.JIRA_IDS}"]) {
              sh '''
                export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
                
                # Update config.env with Jenkins parameter value
                sed -i "s/^COMMIT_FILTER_MODE=.*/COMMIT_FILTER_MODE=$COMMIT_FILTER_MODE/" ./config.env
                
                . ./config.env
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo " Filter Mode: $COMMIT_FILTER_MODE"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                bash scripts/detect_services.sh "${JIRA_IDS}"
                bash scripts/run_all_analyses.sh "${JIRA_IDS}"
              '''
            }
          }
        }
      }
    }
  }

  post {
    success {
      archiveArtifacts artifacts: 'pr-analysis/**/*.json', allowEmptyArchive: true
      sh 'echo "✅ Done — download summary.json from Build Artifacts"'
    }
    failure {
      sh 'echo "❌ Failed — check Console Output above"'
    }
  }
}